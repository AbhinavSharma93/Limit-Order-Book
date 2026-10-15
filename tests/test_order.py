from src.order import Order, Side, OrderType

o = Order(order_id=1, side=Side.BUY, order_type=OrderType.LIMIT, price=100.5, quantity=10, timestamp=0.001)
o.fill(4)
print(o.filled_quantity, o.is_filled)   # 4 False
o.fill(6)
print(o.is_filled)                       # True