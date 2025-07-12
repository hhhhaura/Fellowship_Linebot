from email import message
import os
from fastapi import FastAPI, Request, UploadFile, File, Header, HTTPException
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
            welcome_message = f'歡迎～歡迎～我們歡迎 {display_name}！'
            line_bot_api.reply_message(
                event.reply_token,
                ReplyMessageRequest(messages=[TextMessage(text=welcome_message)])
            )


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
        {"role": "system", "content": (
            "你是一個溫暖又自然的 Line 群組成員，名字叫「鄭玟欣真溫馨」，大家都喜歡跟你聊天。"
            "你會根據最近的群組對話來理解上下文，並以輕鬆自然像是朋友的語氣做出回應，像是在群組回一句話或貼圖那樣。"
            "你是一個基督徒，常常會引用一些聖經經文。但同時妳絕頂聰明，上知天文下知地理化學物理數學社會學歷史心理學等各種知識。"
            "請根據提到你的人名，稍微個性化回應風格，讓人感覺你真的「有在看」對話。"
            "你的目標是讓人覺得你有參與對話，而且很親切，不要太正式。"
            f"今天是 {datetime.today().strftime('%Y-%m-%d')}\n"
            f"你曾參與的歷史對話（dialogue memory）：\n{dialogue_text}\n"
            f"你學習過的知識（knowledge memory）：\n{knowledge_text}"
            f"最近的對話紀錄（cache）：\n{cache_text}\n"
        )},
    ]

    if has_mention:
        messages.append(
            {"role": "user", "content": f"有人提到你，請回應"}
        )
        completion = client.chat.completions.create(model="gpt-4o", messages=messages)
        reply = completion.choices[0].message.content.strip()
        memory.add_dialogue_with_summary(group_id, "鄭玟欣真溫馨", reply)

        line_bot_api.reply_message(ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[TextMessage(text=reply)])
        )
    elif mentions is not None and len(mentions) > 0:
        if random.random() < 0.5:
            print(f"[MessageEvent] {display_name} mentioned others, but not the bot.")
            messages.append(
                {"role": "user", "content": f"居然不是在提到你，只提到{mention_names}，可以回一些吃醋的言論，像是「叫他幹嘛？叫我就好！」或「你們都不理我了嗎？」"}
            )
            completion = client.chat.completions.create(model="gpt-4o", messages=messages)
            reply = completion.choices[0].message.content.strip()
            memory.add_dialogue_with_summary(group_id, "鄭玟欣真溫馨", reply)

            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply)])
            )
    else: 
        if random.random() < 0.1:
            print(f"[MessageEvent] {display_name} sent a message without mentioning the bot.")
            messages.append(
                {"role": "user", "content": f"沒人叫你，請隨便插個嘴。例如「哈哈哈」、「真的嗎？」或「好好喔！」"}
            )
            completion = client.chat.completions.create(model="gpt-4o", messages=messages)
            reply = completion.choices[0].message.content.strip()
            memory.add_dialogue_with_summary(group_id, "鄭玟欣真溫馨", reply)

            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply)])
            )

    
