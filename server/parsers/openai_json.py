import json
from .base import BaseParser

class OpenAIMessagesParser(BaseParser):
    name = 'openai_json'
    display_name = 'OpenAI Messages JSON'
    file_extensions = ['.json']

    def detect(self, raw_content: str) -> bool:
        try:
            data = json.loads(raw_content)
            if isinstance(data, list) and len(data) > 0:
                return all(isinstance(m, dict) and 'role' in m and 'content' in m for m in data)
            if isinstance(data, dict) and 'messages' in data:
                msgs = data['messages']
                return isinstance(msgs, list) and len(msgs) > 0 and all(isinstance(m, dict) and 'role' in m for m in msgs)
            return False
        except (json.JSONDecodeError, TypeError):
            return False

    def parse(self, raw_content: str) -> list[dict]:
        data = json.loads(raw_content)
        if isinstance(data, list):
            return [{'role': m['role'], 'content': m['content']} for m in data]
        if isinstance(data, dict) and 'messages' in data:
            return [{'role': m['role'], 'content': m['content']} for m in data['messages']]
        raise ValueError('Unrecognized JSON structure for messages')
