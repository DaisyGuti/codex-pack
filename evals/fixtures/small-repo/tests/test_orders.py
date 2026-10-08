from api.orders import list_orders


def test_lists_every_order(conn):
    orders = list_orders(conn)
    assert [o["total_cents"] for o in orders] == [1250]
