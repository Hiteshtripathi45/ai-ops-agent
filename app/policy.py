def check_refund_policy(amount: float) -> str:
    """
    Returns one of: "auto_approve", "needs_approval", "needs_human_review"
    """
    if amount < 20:
        return "auto_approve"
    elif amount <= 200:
        return "needs_approval"
    else:
        return "needs_human_review"