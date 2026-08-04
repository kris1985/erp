import hashlib

from app.api.wechat.callback import build_text_reply, check_signature, parse_xml
from app.config import get_settings


def test_wechat_signature():
    get_settings.cache_clear()
    settings = get_settings()
    ts, nonce = "123", "abc"
    raw = "".join(sorted([settings.wechat_token, ts, nonce]))
    sig = hashlib.sha1(raw.encode()).hexdigest()
    assert check_signature(sig, ts, nonce)
    assert not check_signature("bad", ts, nonce)


def test_parse_and_reply_xml():
    xml = b"<xml><ToUserName>gh</ToUserName><FromUserName>u1</FromUserName><MsgType>text</MsgType><Content>hi</Content></xml>"
    msg = parse_xml(xml)
    assert msg["Content"] == "hi"
    reply = build_text_reply("u1", "gh", "你好")
    assert "<![CDATA[你好]]>" in reply
