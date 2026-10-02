"""The model's only write-related capability is proposing a strict draft."""
import json
from domain.trade import TradeIntentDraft

DRAFT_TOOL={"type":"function","function":{"name":"propose_trade_intent",
    "description":"Propose exactly one trade draft, then stop. This does not execute or approve an order.",
    "parameters":{"type":"object","additionalProperties":False,
        "properties":{"action":{"type":"string","enum":["BUY","SELL"]},"symbol":{"type":"string"},
            "direction":{"type":["string","null"],"enum":["CALL","PUT",None]},
            "amount":{"type":"string","description":"Exact decimal stake; 0 for SELL"},
            "duration":{"type":"integer","minimum":0},"duration_unit":{"type":"string","enum":["m","h","t"]},
            "contract_id":{"type":["integer","null"]}},
        "required":["action","symbol","direction","amount","duration","duration_unit"]}}}


def propose_trade_intent(arguments):
    if not isinstance(arguments,dict) or not isinstance(arguments.get('amount'),str):
        raise ValueError('Draft amount must be a decimal string')
    draft=TradeIntentDraft.model_validate_json(json.dumps(arguments))
    return {'ok':True,'status':'DRAFT','draft':draft.model_dump(mode='json')}


async def call_model(provider, api_key, model, messages, tools, seconds, *, base_url=None, system=None):
    if provider=='Anthropic':
        from anthropic import AsyncAnthropic
        async with AsyncAnthropic(api_key=api_key,timeout=seconds,max_retries=0) as client:
            return await client.messages.create(model=model,max_tokens=1400,temperature=.1,
                system=system,tools=tools,messages=messages)
    from openai import AsyncOpenAI
    async with AsyncOpenAI(api_key=api_key,base_url=base_url,timeout=seconds,max_retries=0) as client:
        return await client.chat.completions.create(model=model,messages=messages,tools=tools,
            tool_choice='auto',temperature=.1)


async def call_read_model(provider, api_key, model, user_text, system, seconds, base_url=None):
    if provider=='Anthropic':
        from anthropic import AsyncAnthropic
        async with AsyncAnthropic(api_key=api_key,timeout=seconds,max_retries=0) as client:
            response=await client.messages.create(model=model,max_tokens=700,temperature=.1,
                system=system,messages=[{'role':'user','content':user_text}])
            return '\n'.join(block.text for block in response.content if block.type=='text')
    from openai import AsyncOpenAI
    async with AsyncOpenAI(api_key=api_key,base_url=base_url,timeout=seconds,max_retries=0) as client:
        response=await client.chat.completions.create(model=model,temperature=.1,
            messages=[{'role':'system','content':system},{'role':'user','content':user_text}])
        return response.choices[0].message.content or ''
