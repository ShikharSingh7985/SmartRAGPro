import json
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
        if response.headers.get("content-type", "").startswith("image/"):
            return response.content
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
        st.caption("Text, scanned and mixed PDFs. OCR runs in the worker; vision is optional.")
        with st.form("upload", clear_on_submit=True):
            upload = st.file_uploader("Choose PDF", type=["pdf"])
            mode = st.selectbox(
                "Extraction mode", ["auto", "text-first", "ocr-enabled", "enhanced-multimodal"]
            )
            if st.form_submit_button("Upload PDF", type="primary") and upload:
                with st.spinner("Uploading securely…"):
                    progress = st.progress(0, text="Uploading PDF")
                    api(
                        "POST",
                        "/documents",
                        files={"file": (upload.name, upload, "application/pdf")},
                        data={"extraction_mode": mode},
                    )
                    progress.progress(1.0, text="Upload stored; background ingestion queued")
                st.rerun()
        if not docs:
            st.info("Upload your first PDF to start a conversation.")
        for doc in docs:
            with st.container(border=True):
                left, right = st.columns([5, 1])
                left.write(doc["filename"])
                left.caption(f"{doc['status'].capitalize()} · {doc['page_count']} pages")
                left.caption(
                    f"{doc['extraction_mode']} · {doc['chunk_count']} chunks · "
                    f"{doc['table_count']} tables · {doc['figure_count']} figures"
                )
                if doc["status"] in {"queued", "failed"}:
                    job_history = api("GET", f"/documents/{doc['id']}/jobs")
                    if job_history:
                        job = job_history[0]
                        left.progress(
                            min(1.0, job["pages_processed"] / max(1, job["total_pages"])),
                            text=f"{job['stage']} · attempt {job['attempts']} · "
                            f"{job['pages_processed']}/{job['total_pages']} pages",
                        )
                    if doc["status"] == "failed" and left.button(
                        "Retry ingestion", key="retry-" + doc["id"]
                    ):
                        api("POST", f"/documents/{doc['id']}/retry")
                        st.rerun()
                    if doc["status"] == "queued" and left.button(
                        "Cancel ingestion", key="cancel-" + doc["id"]
                    ):
                        api("POST", f"/documents/{doc['id']}/cancel")
                        st.rerun()
                if doc["error"]:
                    left.warning(doc["error"])
                if doc["status"] == "ready" and left.button(
                    "Reindex document", key="reindex-" + doc["id"]
                ):
                    api("POST", f"/documents/{doc['id']}/reindex")
                    st.rerun()
                if doc["status"] != "deleting" and right.button("Delete", key=doc["id"]):
                    api("DELETE", f"/documents/{doc['id']}")
                    st.session_state.pop("conversation_id", None)
                    st.rerun()
                if doc["page_count"] and doc["status"] != "deleting":
                    with st.expander("Page preview and extracted knowledge"):
                        number = st.number_input(
                            "Page",
                            min_value=1,
                            max_value=doc["page_count"],
                            key="page-" + doc["id"],
                        )
                        if st.button("Load page", key="preview-" + doc["id"]):
                            st.image(api("GET", f"/documents/{doc['id']}/preview/{number}"))
                            details = api("GET", f"/documents/{doc['id']}/pages/{number}")
                            st.caption(f"Extraction: {details['strategy']}")
                            st.json(details["quality"])
                            for warning in details["warnings"]:
                                st.warning(warning)
                            for element in details["elements"]:
                                if element["kind"] == "table":
                                    st.text(element["text"])
                                    st.json(element["data"])
        st.caption(
            "Deleting a source clears derived chat history and keeps the conversation available. "
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
    current = api("GET", f"/conversations/{conversation_id}")
    st.subheader(current["title"])
    if current.get("source_warning"):
        st.warning(current["source_warning"])
    if any(identifier not in ready for identifier in current["document_ids"]):
        st.warning(
            "A selected PDF is unavailable or processing. "
            "Update the selection or wait for it to be ready."
        )
    st.caption("Strict document mode · saved history · responses appear after source verification")
    with st.sidebar, st.expander("Manage current conversation"):
        with st.form("manage-" + conversation_id):
            renamed = st.text_input("Title", value=current["title"], max_chars=120)
            scope = st.multiselect(
                "Current documents",
                list(ready),
                default=[
                    identifier for identifier in current["document_ids"] if identifier in ready
                ],
                format_func=lambda value: ready[value],
                key="scope-" + conversation_id,
            )
            if st.form_submit_button("Save title and document selection"):
                api(
                    "PATCH",
                    f"/conversations/{conversation_id}",
                    json={"title": renamed, "document_ids": scope},
                )
                st.session_state.pop("pending", None)
                st.rerun()
        if st.button("Refresh conversation summary"):
            api("POST", f"/conversations/{conversation_id}/summary/refresh")
            st.success("Summary refreshed from saved messages.")
        confirm_delete = st.checkbox("Delete this conversation and its saved history")
        if st.button("Delete conversation", disabled=not confirm_delete):
            api("DELETE", f"/conversations/{conversation_id}")
            st.session_state.pop("conversation_id", None)
            st.session_state.pop("pending", None)
            st.rerun()
    saved_messages = all_items(f"/conversations/{conversation_id}/messages")
    st.download_button(
        "Export conversation",
        json.dumps({"conversation": current, "messages": saved_messages}, indent=2),
        file_name="conversation.json",
        mime="application/json",
    )
    for message in saved_messages:
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
                        if citation.get("model_derived"):
                            st.caption(
                                "Model-derived visual description; verify against the source image."
                            )
                        if citation.get("asset_id"):
                            st.image(
                                api(
                                    "GET",
                                    f"/documents/{citation['document_id']}/assets/{citation['asset_id']}",
                                )
                            )
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
