from fastapi import FastAPI, Request, Header, HTTPException
from linebot import LineBotApi
from linebot.v3.webhook import WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import TextSendMessage
from linebot.webhook import MemberJoinedEvent, MessageEvent
from dotenv import load_dotenv
import os
load_dotenv() 
from openai import OpenAI

# credentials
CHANNEL_ACCESS_TOKEN = os.getenv("CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("CHANNEL_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TARGET_USER_ID = os.getenv("TARGET_USER_ID") 

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

app = FastAPI()


client = OpenAI(
  api_key=OPENAI_API_KEY
)


@app.post("/callback")
async def callback(request: Request, x_line_signature: str = Header(None)):
    body = await request.body()
    body_text = body.decode("utf-8")
    print(f"[Webhook Received Raw] {body_text}")

    try:
        handler.handle(body_text, x_line_signature)
        print("[Webhook Handler Called]")
    except InvalidSignatureError:
        print("[Invalid Signature]")
        raise HTTPException(status_code=400, detail="Invalid signature")
    
    return "OK"


@handler.add(MemberJoinedEvent)
def handle_member_join(event: MemberJoinedEvent):
    print("[MemberJoinedEvent] received")
    group_id = event.source.group_id
    for member in event.joined.members:
        user_id = member.user_id
        if user_id:
            print(f"  >> Joined user: {user_id}")
            # Optionally filter for TARGET_USER_ID
            if user_id is not None:
                profile = line_bot_api.get_group_member_profile(group_id, user_id)
                display_name = profile.display_name
                welcome_message = f'歡迎～歡迎～我們歡迎 {display_name}！'
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text=welcome_message)
                )

@handler.add(MessageEvent)
def handle_message_event(event: MessageEvent):
    print(f"[MessageEvent] received from user {event.source.user_id}")
    
    # Check if the message is a text message and contains mention
    if hasattr(event.message, 'mention') and event.message.mention:
        mentions = event.message.mention.mentionees
        for mentionee in mentions:
            mentioned_user_id = mentionee.user_id
            print(f">> User mentioned: {mentioned_user_id}")
            
            # You can take action based on a specific user being mentioned
            if mentioned_user_id == TARGET_USER_ID:
                profile = line_bot_api.get_group_member_profile(event.source.group_id, event.source.user_id)
                display_name = profile.display_name
                completion = client.chat.completions.create(
                    model="gpt-4o-mini",
                    store=True,
                    messages=[ 
                        { "role": "system", "content": "你是一個活潑幽默又溫暖的 Line Bot，名字叫「鄭玟欣真溫馨」。你說話風格自然、親切，總帶點輕鬆幽默的語氣。只要有人提到你（mention 你），你就會馬上回覆他們。每次回應都要加上一則冷笑話，笑話可以是日常、無厘頭、諧音梗，讓人哭笑不得但又覺得你很可愛。你也會根據提到你的人名（我會告訴你是誰）稍微個人化回應內容，讓大家感受到你有在「聽」。請記得，冷笑話是你的特色，每次回應都不能忘！" },
                        {"role": "user", "content": f"{display_name}說：「{event.message.text.strip()}」"}
                    ]
                )
                reply_message = completion.choices[0].message.content

                print(reply_message)
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text=f'{reply_message}')
                )
                return
            else:
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text=f'叫他幹嘛！？叫我就好')
                )
                return

    # Fallback or other logic
    if event.message.text.strip() == '鄭玟欣妳好棒ㄛ':
        reply_message = TextSendMessage(text='沒錯ㄛ，我好棒ㄛ！')
        line_bot_api.reply_message(event.reply_token, reply_message)