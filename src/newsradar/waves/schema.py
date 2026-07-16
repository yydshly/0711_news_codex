from pydantic import BaseModel, ConfigDict, Field, field_validator


class WaveProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    name: str = Field(min_length=1, max_length=120)
    window_hours: int = Field(ge=1, le=168)
    trend_days: int = Field(ge=1, le=30)
    required_roles: tuple[str, ...] = Field(min_length=1)
    source_ids: tuple[str, ...] = Field(min_length=1)

    @field_validator("required_roles", "source_ids")
    @classmethod
    def reject_duplicates(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            roles = {"discovery", "engagement", "evidence", "context"}
            field = "role" if values and values[0] in roles else "source id"
            raise ValueError(f"duplicate {field}")
        return values
