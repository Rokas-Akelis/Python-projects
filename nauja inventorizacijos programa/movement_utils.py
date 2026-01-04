# movement_utils.py
from models import Movement, Product


def record_movement(session, product: Product, change: int, source: str, note: str | None = None):
    """
    Užregistruoja judėjimą ir atnaujina produkto quantity.
    """
    if change == 0:
        return

    product.quantity = (product.quantity or 0) + change

    movement = Movement(
        product_id=product.id,
        change=change,
        source=source,
        note=note,
    )
    session.add(movement)
    session.add(product)
