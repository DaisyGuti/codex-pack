from api.auth import login


def test_good_password_logs_in(conn):
    code, payload = login(conn, "email=ada%40example.com&password=correct+horse")
    assert code == 200 and payload == {"user_id": 1}


def test_wrong_password_is_refused(conn):
    code, _ = login(conn, "email=ada%40example.com&password=nope")
    assert code == 401
