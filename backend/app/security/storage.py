from uuid import UUID


def owned_key(key: str, user_id: UUID, document_id: UUID) -> bool:
    return key == f"{user_id}/{document_id}.pdf" or (
        key.startswith(f"{user_id}/{document_id}/assets/")
        and ".." not in key
        and "\\" not in key
        and "\x00" not in key
    )
