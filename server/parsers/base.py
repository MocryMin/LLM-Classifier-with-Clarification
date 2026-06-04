from abc import ABC, abstractmethod

class BaseParser(ABC):
    name: str = ''
    display_name: str = ''
    file_extensions: list[str] = []

    @abstractmethod
    def detect(self, raw_content: str) -> bool:
        """Return True if this parser can handle the content."""
        ...

    @abstractmethod
    def parse(self, raw_content: str) -> list[dict]:
        """Parse content into standard OpenAI messages format."""
        ...
