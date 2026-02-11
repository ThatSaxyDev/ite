from client.llm_client import LLMClient
import asyncio


async def main():
    client = LLMClient()
    messages = [
        {
            "role": "user",
            "content": "Hello",
        }
    ]
    async for event in client.chat_completion(messages, True):
        print(event)
    print("Done")


asyncio.run(main())
