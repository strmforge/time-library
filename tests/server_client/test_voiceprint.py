"""The user's own words, told from what the user pasted in."""

from __future__ import annotations

from test_distill import fake, lab, memory, reply  # noqa: F401  (fixtures)
from tl_server.voiceprint import relayed, voice_of

PASTED = """claude的反馈
我已经核实了这一轮的改动,结论如下:

## 一、已验证
- ✅ 测试全部通过,`pytest -q` 198 passed
- ✅ 部署到 NAS 后 `/api/v1/health` 返回正常

## 二、建议
**以后发版前先跑完全部测试**,不要跳过任何一项。我检查了 `deploy/nas/Dockerfile`,构建参数也对得上。
""" * 2
OWN = """我想了一下,服务端还是放在 NAS 的 Docker 应用层,不要装进系统底层。原因有三个:
一、系统底层升级飞牛的时候容易被覆盖;
二、Docker 里卸载干净;
三、以后换机器直接搬 data 文件夹就行。
你按这个改,改完告诉我。另外回答问题的时候先给结论,再展开讲细节和理由,这个以后都这样。"""
CODEX_TURN = ("# Response annotations:\nEarlier Codex said: 端口用 9850,不要改\n"
              '<response-annotations>\n[{"text": "端口用 9850", "annotation": "这条要改,9850 被飞牛占了"}]\n</response-annotations>\n\n'
              "# Browser comments:\nTarget path: div > main\nComment:\n这个按钮跳到旧版了\n\n"
              "## My request for Codex:\n端口改成 9851,别的不动")


def test_a_pasted_report_is_told_from_the_users_own_long_message():
    assert relayed(PASTED) and not relayed(OWN)
    assert not relayed("claude的反馈:挺好")  # short: nothing to go on
    assert relayed("拆开这个4000多星的项目 原创 开源星探 开源星探 2026年5月20日 07:12 湖北\n" + "正文" * 200)  # a pasted article
    assert voice_of("user", CODEX_TURN, "端口改成 9851") == "user"
    assert voice_of("user", CODEX_TURN, "端口用 9850,不要改") == "relayed"  # the harness's context above the request
    assert voice_of("user", CODEX_TURN, "9850 被飞牛占了") == "user"  # but the user's own comments in it are theirs
    assert voice_of("user", CODEX_TURN, "这个按钮跳到旧版了") == "user"
    assert voice_of("assistant", "好的", "好的") == "assistant"
    topped = "这何止是人好读啊,比你之前的好读多了\n\n" + PASTED
    assert voice_of("user", topped, "这何止是人好读啊") == "user"  # the line the user wrote on top of a paste
    assert voice_of("user", topped, "以后发版前先跑完全部测试") == "relayed"


def test_a_preference_resting_only_on_a_paste_is_not_the_users(lab):
    lab.assign(lab.source())
    lab.say("s1", ("user", PASTED), ("assistant", "收到"), ("user", OWN), ("user", CODEX_TURN))
    lab.fake.replies.append(reply(
        memory("用户要求发版前先跑完全部测试", (1, "以后发版前先跑完全部测试"), kind="preference"),
        memory("用户要求回答先给结论再展开", (3, "回答问题的时候先给结论,再展开讲细节和理由"), kind="preference"),
        memory("用户要求端口改成 9851", (4, "端口改成 9851,别的不动"), (4, "端口用 9850,不要改"), kind="decision"),
    ))
    lab.run()
    assert "[1] 用户(转贴):" in str(lab.prompts()[-1]) and "[3] 用户:" in str(lab.prompts()[-1])
    found = {m["statement"]: m for m in lab.call("GET", "/api/v1/admin/memories")[1]["memories"]}
    pasted, own, port = (found["用户要求发版前先跑完全部测试"], found["用户要求回答先给结论再展开"], found["用户要求端口改成 9851"])
    detail = lab.call("GET", f"/api/v1/admin/memories/{pasted['id']}")[1]
    assert detail["evidence"][0]["voice"] == "relayed" and "不是用户本人的说法" in detail["note"]
    assert lab.call("GET", f"/api/v1/admin/memories/{own['id']}")[1]["note"] == ""
    voices = {item["quote"]: item["voice"] for item in lab.call("GET", f"/api/v1/admin/memories/{port['id']}")[1]["evidence"]}
    assert voices == {"端口改成 9851,别的不动": "user", "端口用 9850,不要改": "relayed"}

    recalled = {m["statement"]: m for m in lab.device("POST", "/api/v1/recall", {"query": "发版前先跑完全部测试", "limit": 5})[1]["memories"]}
    assert recalled["用户要求发版前先跑完全部测试"]["evidence"][0]["voice"] == "relayed"
    assert "不是用户本人的说法" in recalled["用户要求发版前先跑完全部测试"]["note"]

    # Quotes stored before voices were judged are judged once, in the background.
    with lab.distiller._store._tx() as db:
        db.execute("UPDATE memory_evidence SET voice = ''")
        db.execute("UPDATE memories SET user_quoted = 1")
        db.execute("DELETE FROM meta WHERE key = 'evidence_voices'")
    assert lab.distiller.stamp_voices() == 4 and lab.distiller.stamp_voices() == 0
    assert lab.call("GET", f"/api/v1/admin/memories/{pasted['id']}")[1]["evidence"][0]["voice"] == "relayed"
    with lab.distiller._store.reading() as db:
        quoted = {row[0]: row[1] for row in db.execute("SELECT id, user_quoted FROM memories")}
    assert (quoted[pasted["id"]], quoted[own["id"]], quoted[port["id"]]) == (0, 1, 1)
