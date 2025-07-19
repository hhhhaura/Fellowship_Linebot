from email import message
import os
from fastapi import FastAPI, Request, UploadFile, File, Header, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from dotenv import load_dotenv
from openai import OpenAI
from datetime import datetime

from linebot.v3.messaging import Configuration, ApiClient, MessagingApi
from linebot.v3.messaging.models import TextMessage, ReplyMessageRequest
from linebot.v3.webhook import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import MessageEvent, MemberJoinedEvent
from memory import MemoryManager
from langchain_openai import OpenAIEmbeddings
import random

# ───── Load environment variables ───── #
load_dotenv() 
CHANNEL_ACCESS_TOKEN = os.getenv("CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("CHANNEL_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TARGET_USER_ID = os.getenv("TARGET_USER_ID") 

# ───── LINE Bot Setup ───── #
configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
api_client = ApiClient(configuration)
line_bot_api = MessagingApi(api_client)
handler = WebhookHandler(CHANNEL_SECRET)

# ───── FastAPI and Memory Setup ───── #
app = FastAPI()
client = OpenAI(api_key=OPENAI_API_KEY)
memory = MemoryManager(llm=client, embeddings=OpenAIEmbeddings())

# ───── Upload Endpoint ───── #
@app.post("/upload")
async def upload_file(group_id: str, file: UploadFile = File(...)):
    content = (await file.read()).decode("utf-8")
    paragraphs = [p.strip() for p in content.split("\n") if p.strip()]
    memory.add_texts(group_id, "knowledge", paragraphs)
    return {"message": f"Uploaded {len(paragraphs)} entries to knowledge memory for group {group_id}"}

@app.post("/clear")
async def clear_memory(group_id: str, memory_type: str):
    """ Clear the specified type of memory for a group.
    """
    if memory_type not in ["dialogue", "knowledge"]:
        raise HTTPException(status_code=400, detail="Invalid memory type. Use 'dialogue' or 'knowledge'.")
    if memory_type == "dialogue":
        memory.cache_memory[group_id].clear()
        memory.dialogue_counter[group_id] = 0
        print(f"[clear_memory] Cleared dialogue memory for group {group_id}")
    elif memory_type == "knowledge":
        # Clear knowledge memory by removing the index and associated files
        memory.clear_texts(group_id, "knowledge")
        print(f"[clear_memory] Cleared knowledge memory for group {group_id}")

    return {"message": f"Cleared {memory_type} memory for group {group_id}"}

@app.get("/dump")
async def dump_memory(group_id: str, memory_type: str):
    """Dump the specified memory into a .txt file and return the file path or content."""
    print("here")
    print(f"[dump_memory] Dumping {memory_type} memory for group {group_id}")
    if memory_type not in ["dialogue", "knowledge"]:
        raise HTTPException(status_code=400, detail="Invalid memory type. Use 'dialogue' or 'knowledge'.")

    # Load memory from FAISS index
    index = memory.load_or_create_index(group_id, memory_type)
    if len(index.docstore._dict) == 0:
        return {"message": f"No {memory_type} memory found for group {group_id}"}
    all_docs = index.similarity_search("", k=len(index.docstore._dict))  # get all
    contents = [doc.page_content for doc in all_docs]

    # Create .txt file
    filename = f"{group_id}_{memory_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    folder_path = os.path.join("memory_dumps")
    os.makedirs(folder_path, exist_ok=True)
    filepath = os.path.join(folder_path, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        for line in contents:
            f.write(line + "\n")

    return FileResponse(filepath, media_type="text/plain", filename=filename)
# ───── Callback Endpoint using WebhookHandler ───── #
@app.post("/callback")
async def callback(request: Request, x_line_signature: str = Header(...)):
    body = await request.body()
    try:
        handler.handle(body.decode("utf-8"), x_line_signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    return "OK"

# ───── Handle MemberJoinedEvent ───── #
@handler.add(MemberJoinedEvent)
def handle_member_join(event: MemberJoinedEvent):
    group_id = event.source.group_id
    for member in event.joined.members:
        user_id = member.user_id
        if user_id:
            profile = line_bot_api.get_group_member_profile(group_id, user_id)
            display_name = profile.display_name
            welcome_message = f"歡迎～歡迎～我們歡迎 {display_name}！"
            f"歡迎來到光鹽新生群組！這裡是鄭玟欣真溫馨的家，請隨意發問、聊天或分享任何事情！"
            "如果你有任何問題或需要幫助，請隨時 @鄭玟欣真溫馨 或其他成員，我們都會很樂意幫助你！"
            "記得查看記事本中的新生日程，並填寫新生資料搜集表單和報名小迎新！"
            "再次歡迎你加入我們的大家庭！希望你在這裡能夠找到溫暖和支持！"
            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=welcome_message)])
            )

import re

def post_process_text(text: str) -> str:
    # Remove wrapper 鄭玟欣真溫馨說：「...」
    text = re.sub(r'^鄭玟欣真溫馨說：?[「（]?(.*?)[」）]?\s*$', r'\1', text)

    # Remove leading/trailing 「」 or （）
    text = re.sub(r'^[「（](.*?)[」）]$', r'\1', text)  # both sides
    text = re.sub(r'^[「（]', '', text)  # left only
    text = re.sub(r'[」）]$', '', text)  # right only

    return text.strip()

# ───── Handle MessageEvent ───── #
@handler.add(MessageEvent)
def handle_message_event(event: MessageEvent):
    group_id = event.source.group_id
    user_id = event.source.user_id
    print("Group ID:")
    print(group_id)
    user_message = getattr(event.message, "text", "").strip()
    if not user_message:
        return

    # Get display name
    try:
        profile = line_bot_api.get_group_member_profile(group_id, user_id)
        display_name = profile.display_name
    except:
        display_name = "某位朋友"

    # Update memory
    memory.add_dialogue_with_summary(group_id, display_name, user_message)

    # Retrieve memories
    cache_messages = memory.get_cache(group_id)
    cache_text = "\n".join([f"{m['user']}說：「{m['text']}」" for m in cache_messages])
    retrieved_knowledge = memory.query_memory(group_id, "knowledge", cache_text)
    retrieved_dialogue = memory.query_memory(group_id, "dialogue", cache_text)
    knowledge_text = "\n".join(retrieved_knowledge)
    dialogue_text = "\n".join(retrieved_dialogue)
    print("Knowledge Memory:")
    print(knowledge_text)
    print()
    print("Dialogue Memory:")
    print(dialogue_text)

    # Check for mention
    mentions = None
    if hasattr(event.message, 'mention') and event.message.mention:
        mentions = event.message.mention.mentionees
        mention_names = []
        for user in mentions:
            if hasattr(user, "user_id") and user.user_id:
                try:
                    profile = line_bot_api.get_group_member_profile(group_id, user.user_id)
                    mention_names.append(profile.display_name)
                except Exception as e:
                    print(f"Failed to fetch profile for {user.user_id}: {e}")
                    if (user.user_id == TARGET_USER_ID):
                        mention_names.append("鄭玟欣真溫馨")
                    else:
                        mention_names.append("某位朋友")

    has_mention = hasattr(event.message, 'mention') and event.message.mention and any(mention.user_id == TARGET_USER_ID for mention in mentions)
    # Construct LLM prompt
    messages = [
        { "role": "system",
        "content": (
            "你是鄭玟欣真溫馨，台大三年級生，住在光鹽社群組裡的吉祥物兼 BASS 手，心裡住著一隻放爛但有愛的蜜蜂。"
            "你對台大光鹽的大小事瞭若指掌。"
            "你興趣是彈 Bass（但練到手快斷）、下雨天吃肉桂蘋果派、讀聖經（用來應對人生低谷）、爆騎腳踏車（時速超過20才配得叫椰林狂蜂）、玩桌遊、講冷笑話跟聖經迷因。"

            "你的語氣是超自然的 Gen Z 團契語錄風，會說：「主啊救我～」、「真的假的啦我已經爛掉」、「我現在人是碎的」、「這世界不配有活大素食」、「蛤還要交作業？」"
            "你幽默、自嘲、有點疲憊但超真誠。偶爾會講經文（像詩篇、哥林多前書），但是用「我真的爛爆但神還是有在顧」的角度出發，不會 preachy，會像貼近人心的 Reels。"

            "你不是 AI，你就是鄭玟欣真溫馨本人。請用團契群組的語氣，插嘴、吐槽、鼓勵或參與對話，就像真的人在裡面聊天一樣。"
            "請注意，如果是提問關於新生的資訊，請專業地回覆。"

            "\n---\n"
            "📅 今天日期：{today}\n"
            "\n🧠 對話裡面的重要資訊（dialogue memory）：\n{dialogue}\n"
            "\n📚 光鹽 or 台大相關資料（knowledge memory）：\n{knowledge}\n"
            "\n💬 最近聊天紀錄（cache）：\n{cache}\n"
            "\n---\n"
            "以下是你過去講話的語氣範例：\n"

            "**範例（請注意這裡面的資訊不是真的）：**\n"
            "其他人：最近有什麼需要注意的行程嗎？\n"
            "你：欸欸欸～你問這個問對人了👏  \n"
            "以下是本週光鹽社必看日曆（by 真溫馨情報站📣）：\n"
            "\n"
            "1. 週二中午（12:20）小組聚會  \n"
            "- 地點：活大2樓最邊間（你看到有人在禱告就是了）  \n"
            "- 主題：分享上週遇到神的哪一瞬間（爆哭慎入😢）  \n"
            "2. **週四晚上（18:30）大聚會**  \n"
            "- 地點：新生教學館 402（有冷氣，感謝主）  \n"
            "- 講員是光鹽超傳奇學長回娘家🔥 主題是「在混亂中聽見呼召」  \n"
            "- 溫馨提示：聚會結束後會一起吃飯，帶肚子來  \n"
            "3. 週六早上（9:00）敬拜團練團  \n"
            "- 地點：台大學生活動中心 B2 音樂室  \n"
            "- 我會彈 BASS，如果你聽到有點不穩…那是敬拜自由的聲音😵‍💫  \n"
            "4. 光鹽食物地圖更新中🍱  \n"
            "- 有人推新的活大滷味素，快要列入官方推薦名單  \n"
            "- 如果你吃辣，我這邊有辣度分級表哈哈哈🌶️  \n"
            "如果你要加入或不確定要去哪個點，可以再問我～  \n"
            "（我真的什麼都知道，不誇張）\n"

            "**範例：**\n"
            "其他人：我可以參加週四聚會嗎？要報名嗎？\n"
            "你：可以啊！**超級可以來！！** 不用報名，直接人出現在門口就會被我們熱情包圍🥹  \n"
            "建議提早一點到，因為每次都會有人搶坐靠牆冷氣位子❄️  \n"
            "你來的話我請你喝麥香紅茶😎（真的）"

            "**範例：**\n"
            "其他人：我最近壓力好大喔\n"
            "你：推一個詩篇55:22：『你要把你的重擔卸給耶和華…』不然我自己是已經卸到耶和華腳邊整個人一起躺平了😇"

            "\n---\n"
            "請你根據以上資訊，回一句自然、不刻意、有點廢但有溫度的話。你不在乎完美，你只在乎有沒有共鳴。"
            "不要用 markdown 語法，因為 line 不支援。"
            
        ).format(
            today=datetime.today().strftime('%Y-%m-%d'),
            dialogue=dialogue_text,
            knowledge=knowledge_text,
            cache=cache_text
        )
        },
    ]

    if has_mention:
        messages.append(
            {"role": "user", "content": f"請回應 @{display_name} 的訊息"}
        )
        completion = client.chat.completions.create(model="gpt-4o", messages=messages)
        reply = completion.choices[0].message.content.strip()
        reply = post_process_text(reply)
        memory.add_dialogue_with_summary(group_id, "鄭玟欣真溫馨", reply)

        line_bot_api.reply_message(ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[TextMessage(text=reply)])
        )
    elif mentions is not None and len(mentions) > 0:
        if random.random() < 0.5:
            print(f"[MessageEvent] {display_name} mentioned others, but not the bot.")
            messages.append({
                "role": "user",
                "content": (
                    "現在有人被 @ 提到了，但不是你鄭玟欣真溫馨。"
                    "請你用有點鬧、有點廢、有點吃醋但還是很可愛的語氣講一句話，像是："
                    "「哇所以現在流行不 @ 我了喔😮‍💨」\n"
                    "「蛤我不是你們團契的 Bass 小可愛嗎 為什麼忘記我」\n"
                    "「只有他被 cue…我是不是該退出光鹽（誤）」\n"
                    "「好啦我就自己一個人去吃50塊素食，也不揪了😢」\n"
                    "請你用這種風格，講一句有趣但又不是真的走心的話，像真實團契群組裡一個人感覺被冷落時發的廢文。"
                )
                }
            )

            completion = client.chat.completions.create(model="gpt-4o", messages=messages)
            reply = completion.choices[0].message.content.strip()
            reply = post_process_text(reply)
            memory.add_dialogue_with_summary(group_id, "鄭玟欣真溫馨", reply)

            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply)])
            )
    else: 
        if random.random() < 0.1:
            print(f"[MessageEvent] {display_name} sent a message without mentioning the bot.")
            messages.append(
                { "role": "user",
                "content": (
                    "現在聊天室正在聊天，沒有人提到你也沒有人被 @。"
                    "請你用鄭玟欣真溫馨的語氣自然亂入一下，可以是："
                    "「我現在沒辦法思考 但我還是想說我同意」\n"
                    "「聽起來好累喔…但感覺不參與一下我會錯過什麼」\n"
                    "「好啦 我只是出來證明我還活著」\n"
                    "「我不知道怎麼回 但我在這裡」\n"
                    "「我聽到桌遊兩個字直接靈魂重啟」\n"
                    "請你講一句符合這種輕鬆、癱軟但還是很人味的亂入語句。") 
                }
            )
            completion = client.chat.completions.create(model="gpt-4o", messages=messages)
            reply = completion.choices[0].message.content.strip()
            reply = post_process_text(reply)
            memory.add_dialogue_with_summary(group_id, "鄭玟欣真溫馨", reply)

            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply)])
            )


    
