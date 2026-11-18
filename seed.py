from app.database import SessionLocal, Base, engine
from app import models


def seed():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()

    john = models.Customer(name="John Doe", email="john@example.com")
    priya = models.Customer(name="Priya Sharma", email="priya@example.com")
    db.add_all([john, priya])
    db.commit()
    db.refresh(john)
    db.refresh(priya)

    order1 = models.Order(customer_id=john.id, item="Wireless Mouse", amount=49.99)
    order2 = models.Order(customer_id=priya.id, item="Keyboard", amount=89.99)
    order3 = models.Order(customer_id=john.id, item="USB Cable", amount=15.00)
    order4 = models.Order(customer_id=priya.id, item="Monitor", amount=450.00)
    db.add_all([order1, order2, order3, order4])
    db.commit()
    for o in (order1, order2, order3, order4):
        db.refresh(o)

    payments = [
        models.Payment(order_id=order1.id, amount=49.99),   # payment 1
        models.Payment(order_id=order1.id, amount=49.99),   # payment 2 (duplicate, needs approval)
        models.Payment(order_id=order2.id, amount=89.99),   # payment 3 (normal)
        models.Payment(order_id=order3.id, amount=15.00),   # payment 4
        models.Payment(order_id=order3.id, amount=15.00),   # payment 5 (duplicate, auto-approve)
        models.Payment(order_id=order4.id, amount=450.00),  # payment 6
        models.Payment(order_id=order4.id, amount=450.00),  # payment 7 (duplicate, human review)
    ]
    for p in payments:
        db.add(p)
        db.commit()

    db.close()


if __name__ == "__main__":
    seed()
    print("Database seeded.")
    print("Order 1: $49.99 duplicate  -> needs approval")
    print("Order 2: $89.99 single     -> no duplicate")
    print("Order 3: $15.00 duplicate  -> auto-approve")
    print("Order 4: $450.00 duplicate -> human review")