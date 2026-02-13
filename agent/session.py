from datetime import datetime
import uuid
from tools.registry import create_default_registry
from context.manager import ContextManager
from client.llm_client import LLMClient
from config.config import Config

class Session:
    def __init__(self, config: Config):
       self.config = config
       self.client = LLMClient(config=self.config)
       self.context_manager = ContextManager(config=self.config)
       self.tool_registry = create_default_registry()
       self.session_id = str(uuid.uuid4())
       self.created_at = datetime.now()
       self.updated_at = datetime.now()

       self._turn_count = 0
    
    def increment_turn(self) -> int:
        self._turn_count += 1
        self.updated_at = datetime.now()
        
        return self.turn_count

