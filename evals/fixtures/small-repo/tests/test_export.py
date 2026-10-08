from services.export import export_orders


def test_exports_the_days_orders(conn):
    sent = []
    feed: list[tuple] = []
    count = export_orders(conn, feed, lambda rows: sent.append(list(rows)), "2000-01-01")
    assert count == 1 and sent == [[(1, 1, 1250, "open")]]
