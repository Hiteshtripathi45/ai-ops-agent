import os
import sys
import json
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
from openai import (
    OpenAI,
    RateLimitError,
    APITimeoutError,
    APIConnectionError,
    InternalServerError,
)

from app.database import SessionLocal
from app import models
from app.policy import check_refund_policy

load_dotenv()

MODEL = "gemini-3.6-flash"

client = OpenAI(
    api_key=os.getenv("GEMINI_API_KEY"),
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
)

SYSTEM_PROMPT = """You are an operations agent for a small business. You resolve customer requests using the tools provided.

Rules:
- Always look up facts with tools before acting. Never guess order, payment or customer details.
- A duplicate payment means two or more successful payments for the same order that together exceed the order amount. Only refund the extra payment, never the original one.
- Refund only when a duplicate is confirmed. If the facts do not support the customer's claim, do not refund; explain why.
- Never try to bypass approval or policy. If a refund needs approval, wait for the result.
- After a successful refund, send the customer a short confirmation email if their email is known.
- If something fails or you are unsure, say so plainly instead of guessing."""


# =====================================================================
# TOOLS (the functions that touch the database)
# =====================================================================

def get_order(order_id: int) -> dict:
    db = SessionLocal()
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    db.close()
    if not order:
        return {"error": f"No order found with id {order_id}"}
    return {
        "id": order.id,
        "customer_id": order.customer_id,
        "item": order.item,
        "amount": order.amount,
        "status": order.status,
    }


def get_customer(customer_id: int) -> dict:
    db = SessionLocal()
    customer = db.query(models.Customer).filter(models.Customer.id == customer_id).first()
    db.close()
    if not customer:
        return {"error": f"No customer found with id {customer_id}"}
    return {"id": customer.id, "name": customer.name, "email": customer.email}


def get_payment_history(order_id: int) -> dict:
    db = SessionLocal()
    payments = db.query(models.Payment).filter(models.Payment.order_id == order_id).all()
    db.close()
    return {
        "order_id": order_id,
        "payments": [{"id": p.id, "amount": p.amount, "status": p.status} for p in payments],
        "count": len(payments),
    }


def issue_refund(payment_id: int, _approved: bool = False) -> dict:
    db = SessionLocal()
    payment = db.query(models.Payment).filter(models.Payment.id == payment_id).first()

    if not payment:
        db.close()
        return {"error": f"No payment found with id {payment_id}"}

    if payment.status == "refunded":
        db.close()
        return {"error": f"Payment {payment_id} was already refunded", "already_refunded": True}

    if payment.status != "success":
        db.close()
        return {"error": f"Payment {payment_id} has status '{payment.status}' and cannot be refunded"}

    decision = check_refund_policy(payment.amount)

    if decision != "auto_approve" and not _approved:
        db.close()
        return {
            "status": "pending_approval",
            "payment_id": payment.id,
            "amount": payment.amount,
            "policy_decision": decision,
            "message": f"Refund of ${payment.amount} for payment {payment.id} requires human approval ({decision}).",
        }

    payment.status = "refunded"
    db.commit()
    db.refresh(payment)
    result = {
        "payment_id": payment.id,
        "order_id": payment.order_id,
        "amount": payment.amount,
        "status": payment.status,
        "message": f"Refund issued for payment {payment.id}",
    }
    db.close()
    return result


def send_email(to: str, subject: str, body: str) -> dict:
    # Mocked: a real system would call an email API (SendGrid, SES, ...)
    print(f"\n--- EMAIL SENT ---\nTo: {to}\nSubject: {subject}\nBody: {body}\n------------------\n")
    return {"status": "sent", "to": to, "subject": subject}


def _tool(name, description, properties, required):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


tools = [
    _tool("get_order", "Fetch an order's details by its order ID",
          {"order_id": {"type": "integer", "description": "The order's ID"}}, ["order_id"]),
    _tool("get_customer", "Fetch a customer's details (including email) by customer ID",
          {"customer_id": {"type": "integer", "description": "The customer's ID"}}, ["customer_id"]),
    _tool("get_payment_history", "Fetch all payments made for a given order, to check for duplicates",
          {"order_id": {"type": "integer", "description": "The order's ID"}}, ["order_id"]),
    _tool("issue_refund", "Issue a refund for a specific payment by its payment ID",
          {"payment_id": {"type": "integer", "description": "The payment's ID to refund"}}, ["payment_id"]),
    _tool("send_email", "Send an email to a customer, e.g. to confirm a refund",
          {
              "to": {"type": "string", "description": "Recipient email address"},
              "subject": {"type": "string", "description": "Email subject line"},
              "body": {"type": "string", "description": "Email body text"},
          },
          ["to", "subject", "body"]),
]

available_tools = {
    "get_order": get_order,
    "get_customer": get_customer,
    "get_payment_history": get_payment_history,
    "issue_refund": issue_refund,
    "send_email": send_email,
}

WRITE_TOOLS = {"issue_refund", "send_email"}  # tools that change the world


# =====================================================================
# TASK LOGGING (persistent record of every run)
# =====================================================================

def create_task(request: str) -> int:
    db = SessionLocal()
    task = models.Task(request=request, status="running")
    db.add(task)
    db.commit()
    db.refresh(task)
    task_id = task.id
    db.close()
    return task_id


def set_task_status(task_id: int, status: str):
    db = SessionLocal()
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if task:
        task.status = status
        db.commit()
    db.close()


def log_step(task_id: int, tool_name: str, args: dict, result: dict):
    db = SessionLocal()
    db.add(models.TaskStep(
        task_id=task_id,
        tool_name=tool_name,
        tool_args=json.dumps(args, default=str),
        result=json.dumps(result, default=str),
    ))
    db.commit()
    db.close()


def finish_task(task_id: int, status: str, answer: str, llm_calls: int):
    db = SessionLocal()
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if task:
        task.status = status
        task.final_answer = answer
        task.llm_calls = llm_calls
        task.finished_at = datetime.now(timezone.utc)
        db.commit()
    db.close()


# =====================================================================
# RELIABILITY: safe tool execution, idempotency, LLM retries
# =====================================================================

def idem_key(tool_name: str, args: dict) -> str:
    """Same tool + same arguments = same key (internal _flags ignored)."""
    clean = {k: v for k, v in (args or {}).items() if not k.startswith("_")}
    return tool_name + ":" + json.dumps(clean, sort_keys=True, default=str)


def execute_tool(tool_name: str, tool_args: dict, executed: dict) -> dict:
    if tool_name not in available_tools:
        return {"error": f"Unknown tool '{tool_name}'"}

    # Security: the LLM must never control internal flags like _approved
    safe_args = {k: v for k, v in tool_args.items() if not k.startswith("_")}

    # Idempotency: a write action with identical arguments only runs once per task
    key = idem_key(tool_name, safe_args)
    if tool_name in WRITE_TOOLS and key in executed:
        return {**executed[key], "duplicate_call_skipped": True}

    try:
        result = available_tools[tool_name](**safe_args)
    except TypeError as e:
        return {"error": f"Invalid arguments for {tool_name}: {e}"}
    except Exception as e:
        return {"error": f"{tool_name} failed: {e}"}

    if (
        tool_name in WRITE_TOOLS
        and "error" not in result
        and result.get("status") != "pending_approval"
    ):
        executed[key] = result

    return result


def call_llm(messages, retries: int = 5):
    for attempt in range(retries):
        try:
            return client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=tools,
                timeout=30,
            )
        except (RateLimitError, APITimeoutError, APIConnectionError, InternalServerError) as e:
            if attempt == retries - 1:
                break
            wait = 2 ** (attempt + 1)  # 2s, 4s, 8s, 16s
            print(f"[LLM error: {type(e).__name__}] retrying in {wait}s (attempt {attempt + 1}/{retries})")
            time.sleep(wait)
    raise RuntimeError("LLM unavailable after retries")


# =====================================================================
# HUMAN APPROVAL
# =====================================================================

def cli_approval(info: dict) -> bool:
    # Never block a non-interactive process (e.g. a uvicorn worker).
    if not sys.stdin.isatty():
        return False
    print(f"\n⚠️  APPROVAL NEEDED: {info['message']}")
    return input("Approve? (yes/no): ").strip().lower() in ("yes", "y")


def save_state(task_id: int, state: dict, pending: dict = None):
    db = SessionLocal()
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if task:
        task.state = json.dumps(state, default=str)
        task.pending = json.dumps(pending) if pending else None
        db.commit()
    db.close()


# =====================================================================
# THE AGENT LOOP (can start fresh, or resume a paused task)
# =====================================================================

def _run_loop(task_id: int, state: dict, approval_handler, verbose: bool, max_turns: int = 8) -> dict:
    """
    approval_handler given -> asks inline (CLI / evaluation).
    approval_handler None  -> pauses: saves state to the DB and returns.
    """
    start = time.time()
    messages = state["messages"]

    def summary(status: str, answer: str = "", **extra) -> dict:
        return {
            "task_id": task_id,
            "status": status,
            "answer": answer,
            "tools_called": state["tools_called"],
            "approval_requested": state["approval_requested"],
            "llm_calls": state["llm_calls"],
            "tokens": state["tokens"],
            "duration": round(time.time() - start, 2),
            **extra,
        }

    def finish(status: str, answer: str) -> dict:
        finish_task(task_id, status, answer, state["llm_calls"])
        if status == "needs_review":
            print(f"[NOTIFY HUMAN] Task {task_id} needs review: {answer}")
        return summary(status, answer)

    for turn in range(max_turns):
        try:
            response = call_llm(messages)
        except Exception as e:
            return finish("needs_review", f"LLM unavailable: {e}")

        state["llm_calls"] += 1
        usage = getattr(response, "usage", None)
        if usage and getattr(usage, "total_tokens", None):
            state["tokens"] += usage.total_tokens

        reply = response.choices[0].message

        assistant_message = {"role": "assistant", "content": reply.content}
        if reply.tool_calls:
            assistant_message["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    # 👇 THIS IS THE FIX FOR GEMINI 3.x 👇
                    "extra_content": {
                        "google": {
                            "thought_signature": "skip_thought_signature_validator"
                        }
                    }
                    # 👆 --------------------------------- 👆
                }
                for tc in reply.tool_calls
            ]
        messages.append(assistant_message)

        if not reply.tool_calls:
            return finish("completed", reply.content or "")

        for idx, tool_call in enumerate(reply.tool_calls):
            name = tool_call.function.name
            try:
                args = json.loads(tool_call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            if not isinstance(args, dict):
                args = {}

            if verbose:
                print(f"[Turn {turn + 1}] Agent calls: {name}({args})")
            state["tools_called"].append(name)

            key = idem_key(name, args)
            state["call_counts"][key] = state["call_counts"].get(key, 0) + 1
            if state["call_counts"][key] > 3:
                return finish("needs_review", f"Agent stuck repeating {name}({args})")

            result = execute_tool(name, args, state["executed"])

            if result.get("status") == "pending_approval":
                state["approval_requested"] = True

                if approval_handler is None:
                    # PAUSE: placeholder result now, real result filled in on resume.
                    # NOTE: we deliberately do NOT log_step here — the step is logged
                    # once, on resume, with the real outcome.
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps({"status": "awaiting_human_approval"}),
                    })
                    msg_index = len(messages) - 1
                    assert messages[msg_index]["tool_call_id"] == tool_call.id

                    pending = {
                        "tool_name": name,
                        "key": key,
                        "args": args,
                        "payment_id": result["payment_id"],
                        "amount": result["amount"],
                        "message": result["message"],
                        "msg_index": msg_index,
                    }

                    # every tool_call in this assistant message needs an answer
                    for other in reply.tool_calls[idx + 1:]:
                        messages.append({
                            "role": "tool",
                            "tool_call_id": other.id,
                            "content": json.dumps({
                                "error": "Not executed: an earlier action is awaiting approval. Retry if still needed."
                            }),
                        })

                    save_state(task_id, state, pending)
                    set_task_status(task_id, "waiting_for_approval")
                    return summary(
                        "waiting_for_approval",
                        pending={k: pending[k] for k in ("payment_id", "amount", "message")},
                    )

                # INLINE approval
                if approval_handler(result):
                    result = issue_refund(result["payment_id"], _approved=True)
                    if verbose:
                        print(f"[Human approved] {result}")
                else:
                    result = {"status": "rejected_by_human", "payment_id": result["payment_id"]}
                    if verbose:
                        print("[Human rejected] Refund denied.")
                state["executed"][key] = result

            log_step(task_id, name, args, result)

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(result),
            })

            state["consecutive_errors"] = state["consecutive_errors"] + 1 if "error" in result else 0
            if state["consecutive_errors"] >= 3:
                return finish("needs_review", f"3 consecutive tool errors, last: {result}")

    return finish("needs_review", f"Exceeded {max_turns} turns without a final answer")


def run_agent(user_message: str, max_turns: int = 8, approval_handler=cli_approval, verbose: bool = True) -> dict:
    task_id = create_task(user_message)
    state = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        "executed": {},
        "call_counts": {},
        "tools_called": [],
        "approval_requested": False,
        "llm_calls": 0,
        "tokens": 0,
        "consecutive_errors": 0,
    }
    return _run_loop(task_id, state, approval_handler, verbose, max_turns)


def resume_agent(task_id: int, approved: bool, verbose: bool = False) -> dict:
    db = SessionLocal()
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        db.close()
        raise ValueError(f"Task {task_id} not found")
    if task.status != "waiting_for_approval":
        status = task.status
        db.close()
        raise ValueError(f"Task {task_id} is '{status}', not waiting for approval")
    state = json.loads(task.state)
    pending = json.loads(task.pending)
    task.status = "running"   # claim it, so a second approve call is rejected
    db.commit()
    db.close()

    if approved:
        result = issue_refund(pending["payment_id"], _approved=True)
    else:
        result = {"status": "rejected_by_human", "payment_id": pending["payment_id"]}

    state["executed"][pending["key"]] = result
    log_step(task_id, pending["tool_name"], pending.get("args", {"payment_id": pending["payment_id"]}), result)
    state["messages"][pending["msg_index"]]["content"] = json.dumps(result)

    return _run_loop(task_id, state, None, verbose)


if __name__ == "__main__":
    result = run_agent(
        "A customer says they were charged twice for order 1 and wants a refund for the duplicate. "
        "Please verify it's a real duplicate and issue the refund for the extra payment."
    )
    print(f"\nStatus: {result['status']}  |  Tools: {result['tools_called']}  |  "
          f"LLM calls: {result['llm_calls']}  |  {result['duration']}s")
    print("Final answer:", result["answer"])