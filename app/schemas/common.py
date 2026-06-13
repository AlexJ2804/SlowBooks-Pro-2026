from pydantic import BaseModel


class MessageResponse(BaseModel):
    message: str


class PaginatedResponse(BaseModel):
    items: list
    total: int
    page: int
    per_page: int
