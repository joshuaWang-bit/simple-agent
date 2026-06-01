# Events will be defined in later stages
from typing import Annotated, Literal

from pydantic import BaseModel, Discriminator


class PlaceholderEvent(BaseModel):
    type: Literal["placeholder"] = "placeholder"


Event = Annotated[
    PlaceholderEvent,
    Discriminator("type"),
]
