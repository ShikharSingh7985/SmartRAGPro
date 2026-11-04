import os
from typing import Any
from uuid import uuid4

import httpx
import streamlit as st

st.set_page_config(page_title="SmartRAG Pro", page_icon="📚", layout="wide")
BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")


def api(method: str, path: str, **kwargs: Any) -> Any:
    headers = (
        {"Authorization": f"Bearer {st.session_state['token']}"}
        if "token" in st.session_state
        else {}
    )
    try:
        response = httpx.request(
            method, BASE_URL + "/api/v1" + path, headers=headers, timeout=180, **kwargs
        )
        if response.status_code == 401 and "token" in st.session_state:
            st.session_state.clear()
            st.warning("Your session expired. Please sign in again.")
            st.stop()
        if response.is_error:
            detail = response.json().get("detail", "Request failed")
            st.error(detail if isinstance(detail, str) else "Please check the form values.")
            st.stop()
        return response.json() if response.content else None
    except (httpx.HTTPError, ValueError):
        st.error("The service is unavailable. Please retry shortly.")
        st.stop()


def all_items(path: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    while True:
        batch = api("GET", path, params={"limit": 100, "offset": len(items)})
        items.extend(batch)
        if len(batch) < 100:
            return items


def auth() -> None:
    st.title("SmartRAG Pro")
    st.caption("Private document conversations with page-level sources")
    login_tab, register_tab = st.tabs(["Sign in", "Create account"])
    with login_tab, st.form("login"):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Sign in", type="primary"):
            result = api("POST", "/auth/login", json={"email": email, "password": password})
            st.session_state["token"] = result["access_token"]
            st.rerun()
    with register_tab, st.form("register"):
        email = st.text_input("Email", key="register_email")
        password = st.text_input(
            "Password (at least 12 characters)", type="password", key="register_password"
        )
        if st.form_submit_button("Create account"):
            api("POST", "/auth/register", json={"email": email, "password": password})
            st.success("Account created. Sign in to continue.")


def main() -> None:
    if "token" not in st.session_state:
        auth()
        return
    user = api("GET", "/auth/me")
    with st.sidebar:
        st.title("📚 SmartRAG Pro")
        st.caption(user["email"])
        page = st.radio("Workspace", ["Chat", "Documents"])
        if st.button("Refresh"):
            st.rerun()
        if st.button("Log out"):
            api("POST", "/auth/logout")
            st.session_state.clear()
            st.rerun()
    docs = all_items("/documents")
    if page == "Documents":
        st.title("Your documents")
        st.caption("Upload digital-text PDFs up to 20 MB. Scanned PDFs need OCR in a later phase.")
        with st.form("upload", clear_on_submit=True):
            upload = st.file_uploader("Choose PDF", type=["pdf"])
            if st.form_submit_button("Upload PDF", type="primary") and upload:
                with st.spinner("Uploading securely…"):
                    api(
                        "POST",
                        "/documents",
                        files={"file": (upload.name, upload.getvalue(), "application/pdf")},
                    )
                st.rerun()
        if not docs:
            st.info("Upload your first PDF to start a conversation.")
        for doc in docs:
            with st.container(border=True):
                left, right = st.columns([5, 1])
                left.write(doc["filename"])
                left.caption(f"{doc['status'].capitalize()} · {doc['page_count']} pages")
                if doc["error"]:
                    left.warning(doc["error"])
                if doc["status"] != "deleting" and right.button("Delete", key=doc["id"]):
                    api("DELETE", f"/documents/{doc['id']}")
                    st.session_state.pop("conversation_id", None)
                    st.rerun()
        st.caption(
            "Deletion also removes conversations based on the document. "
            "Refresh to see job progress."
        )
        return
    st.title("Ask your documents")
    ready = {doc["id"]: doc["filename"] for doc in docs if doc["status"] == "ready"}
    history = all_items("/conversations")
    with st.sidebar:
        selected = st.multiselect(
            "Documents for a new chat", list(ready), format_func=lambda value: ready[value]
        )
        title = st.text_input("Conversation title", value="New conversation", max_chars=120)
        if st.button("New conversation", disabled=not selected):
            result = api("POST", "/conversations", json={"title": title, "document_ids": selected})
            st.session_state["conversation_id"] = result["id"]
            st.session_state.pop("pending", None)
            st.rerun()
        st.subheader("Previous conversations")
        for conversation in history:
            if st.button(conversation["title"], key=conversation["id"]):
                st.session_state["conversation_id"] = conversation["id"]
                st.session_state.pop("pending", None)
                st.rerun()
    conversation_id = st.session_state.get("conversation_id")
    if not conversation_id or conversation_id not in {item["id"] for item in history}:
        st.info(
            "Upload a PDF in Documents, wait until it is ready, then select it to create a chat."
        )
        return
    for message in all_items(f"/conversations/{conversation_id}/messages"):
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message["citations"]:
                with st.expander("Sources"):
                    for citation in message["citations"]:
                        st.text(
                            f"[{citation['source']}] {citation['filename']} "
                            f"· page {citation['page']}"
                        )
                        st.text(citation["excerpt"])
    prompt = st.chat_input("Ask a question grounded in your selected PDFs")
    if prompt:
        st.session_state["pending"] = {"content": prompt, "request_id": str(uuid4())}
    if st.session_state.get("pending"):
        with st.spinner("Finding evidence and preparing an answer…"):
            api(
                "POST",
                f"/conversations/{conversation_id}/messages",
                json=st.session_state["pending"],
            )
        st.session_state.pop("pending")
        st.rerun()


if __name__ == "__main__":
    main()
