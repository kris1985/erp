"""WeChat Official Account webhook + voice ASR adapter."""

from __future__ import annotations

import hashlib
import logging
import xml.etree.ElementTree as ET
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.wechat.asr import asr_adapter
from app.db import get_db
from app.models import Tenant, Worker
from app.services.nlu import handle_chat

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/wechat", tags=["wechat"])


def check_signature(signature: str, timestamp: str, nonce: str) -> bool:
    token = get_settings().wechat_token
    parts = sorted([token, timestamp, nonce])
    digest = hashlib.sha1("".join(parts).encode("utf-8")).hexdigest()
    return digest == signature


def parse_xml(body: bytes) -> dict:
    root = ET.fromstring(body)
    return {child.tag: (child.text or "") for child in root}


def build_text_reply(to_user: str, from_user: str, content: str) -> str:
    # Escape minimal XML entities
    safe = (
        content.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    return f"""<xml>
<ToUserName><![CDATA[{to_user}]]></ToUserName>
<FromUserName><![CDATA[{from_user}]]></FromUserName>
<CreateTime>1</CreateTime>
<MsgType><![CDATA[text]]></MsgType>
<Content><![CDATA[{safe}]]></Content>
</xml>"""



def _default_tenant_id(db: Session) -> int:
    tenant = db.scalar(select(Tenant).where(Tenant.is_active.is_(True)).order_by(Tenant.id))
    if not tenant:
        raise RuntimeError("no tenant")
    return tenant.id


@router.get("/callback")
def verify(
    signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    echostr: str = Query(...),
):
    if check_signature(signature, timestamp, nonce):
        return Response(content=echostr, media_type="text/plain")
    return Response(content="invalid", status_code=403)


@router.post("/callback")
async def callback(
    request: Request,
    signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    db: Session = Depends(get_db),
):
    if not check_signature(signature, timestamp, nonce):
        return Response(content="invalid", status_code=403)

    body = await request.body()
    msg = parse_xml(body)
    msg_type = msg.get("MsgType", "")
    openid = msg.get("FromUserName", "")
    to_user = msg.get("ToUserName", "")

    tenant_id = _default_tenant_id(db)
    text = ""

    if msg_type == "text":
        text = msg.get("Content", "")
    elif msg_type == "voice":
        media_id = msg.get("MediaId", "")
        recognition = msg.get("Recognition")  # 开通语音识别后微信可能直接给
        text = recognition or asr_adapter.recognize(media_id)
        if not text:
            reply = "语音识别失败，请改发文字，例如：230711 红 37码 针车 做了100双"
            return Response(content=build_text_reply(openid, to_user, reply), media_type="application/xml")
    elif msg_type == "event":
        event = msg.get("Event", "").lower()
        if event == "subscribe":
            reply = "欢迎关注铁玉兰管家！请发送：我是张三 13800138000 完成绑定，然后直接语音/文字报工。"
            return Response(content=build_text_reply(openid, to_user, reply), media_type="application/xml")
        reply = "收到事件。"
        return Response(content=build_text_reply(openid, to_user, reply), media_type="application/xml")
    else:
        reply = "暂只支持文字和语音消息。"
        return Response(content=build_text_reply(openid, to_user, reply), media_type="application/xml")

    worker = db.scalar(
        select(Worker).where(Worker.tenant_id == tenant_id, Worker.wechat_openid == openid)
    )
    result = handle_chat(
        db,
        tenant_id=tenant_id,
        text=text,
        worker_id=worker.id if worker else None,
        openid=openid,
    )
    return Response(
        content=build_text_reply(openid, to_user, result["reply"]),
        media_type="application/xml",
    )
