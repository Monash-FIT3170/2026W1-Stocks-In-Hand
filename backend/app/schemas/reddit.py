from pydantic import BaseModel
from typing import Optional

class RedditPostResponse(BaseModel):
    id: str
    title: str
    body: str
    score: int
    upvote_ratio: float
    num_comments: int
    url: str
    external_url: Optional[str]
    author: str
    flair: Optional[str]
    is_self: bool
    created_utc: float
    subreddit: str