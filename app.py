import streamlit as st
import requests
from supabase import create_client, Client
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate

# ==============================
# CONFIG
# ==============================
BACKEND_URL = "https://rag-backend-681419760900.asia-south1.run.app"

st.set_page_config(page_title="RAG Chatbot", layout="wide")

# ==============================
# SUPABASE INIT
# ==============================
@st.cache_resource
def init_supabase() -> Client:
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_KEY"]
    )

supabase = init_supabase()

# ==============================
# SESSION RESTORE
# ==============================
if "session" in st.session_state:
    try:
        supabase.auth.set_session(
            st.session_state.session["access_token"],
            st.session_state.session["refresh_token"]
        )
    except Exception:
        pass

# ==============================
# AUTH STATE
# ==============================
if "user" not in st.session_state:
    st.session_state.user = None

if "viewing_pdf" not in st.session_state:
    st.session_state.viewing_pdf = None

if "messages" not in st.session_state:
    st.session_state.messages = []


# ==============================
# AUTH FLOW
# ==============================
def auth_flow() -> bool:
    st.sidebar.title("Authentication")

    # Logged in
    if st.session_state.user:
        st.sidebar.write(f"Logged in as: {st.session_state.user.email}")

        if st.sidebar.button("Logout"):
            supabase.auth.sign_out()
            st.session_state.user = None
            st.session_state.session = None
            st.rerun()

        return True

    tab1, tab2 = st.sidebar.tabs(["Login", "Signup"])

    # LOGIN
    with tab1:
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Password", type="password", key="login_pass")

        if st.button("Login"):
            try:
                res = supabase.auth.sign_in_with_password({
                    "email": email,
                    "password": password
                })

                st.session_state.user = res.user
                st.session_state.session = {
                    "access_token": res.session.access_token,
                    "refresh_token": res.session.refresh_token
                }

                supabase.auth.set_session(
                    res.session.access_token,
                    res.session.refresh_token
                )

                st.rerun()

            except Exception as e:
                st.error(f"Login failed: {e}")

    # SIGNUP
    with tab2:
        email = st.text_input("Email", key="signup_email")
        password = st.text_input("Password", type="password", key="signup_pass")

        if st.button("Sign Up"):
            try:
                supabase.auth.sign_up({
                    "email": email,
                    "password": password
                })
                st.success("Signup successful. Please login.")
            except Exception as e:
                st.error(f"Signup failed: {e}")

    return False


# ==============================
# STORAGE FUNCTIONS
# ==============================
def upload_to_supabase(file, user_id: str):
    try:
        path = f"{user_id}/{file.name}"

        supabase.storage.from_("pdfs").upload(
            path=path,
            file=file.getvalue(),
            file_options={"content-type": "application/pdf"}
        )

        return path

    except Exception as e:
        st.error(f"Upload failed: {e}")
        return None


# ==============================
# BACKEND CALLS
# ==============================
def process_pdf_backend(file, user_id: str):
    try:
        res = requests.post(
            f"{BACKEND_URL}/process_pdf",
            files={"file": (file.name, file.getvalue(), "application/pdf")},
            data={"user_id": user_id},
            timeout=60
        )

        return res.json()

    except Exception as e:
        st.error(f"Backend error: {e}")
        return None


def search_backend(query: str, user_id: str):
    try:
        res = requests.post(
            f"{BACKEND_URL}/search",
            json={"query": query, "user_id": user_id},
            timeout=60
        )

        return res.json().get("context", "")

    except Exception as e:
        st.error(f"Search error: {e}")
        return ""


# ==============================
# MAIN APP
# ==============================
if auth_flow():

    st.title("📄 RAG Chatbot")

    user_id = st.session_state.user.id

    # --------------------------
    # UPLOAD
    # --------------------------
    uploaded_files = st.file_uploader(
        "Upload PDFs",
        type=["pdf"],
        accept_multiple_files=True
    )

    if uploaded_files and st.button("Process Documents"):
        with st.spinner("Processing..."):
            for file in uploaded_files:
                path = upload_to_supabase(file, user_id)

                if path:
                    process_pdf_backend(file, user_id)

        st.success("Documents processed!")

    # --------------------------
    # DOCUMENT LIST
    # --------------------------
    st.sidebar.markdown("---")
    st.sidebar.subheader("📚 Your Documents")

    try:
        files = supabase.storage.from_("pdfs").list(user_id)
        documents = [f["name"] for f in files]
    except Exception:
        documents = []

    if documents:
        for doc in documents:
            col1, col2 = st.sidebar.columns([8, 2])

            # VIEW
            with col1:
                if st.button(f"📄 {doc}", key=f"view_{doc}"):
                    st.session_state.viewing_pdf = doc

            # DELETE
            with col2:
                if st.button("❌", key=f"del_{doc}"):

                    # Delete from backend
                    requests.post(
                        f"{BACKEND_URL}/delete_pdf",
                        json={"file_name": doc, "user_id": user_id}
                    )

                    # Delete from storage
                    supabase.storage.from_("pdfs").remove(
                        [f"{user_id}/{doc}"]
                    )

                    st.rerun()
    else:
        st.sidebar.info("No documents uploaded.")

    # --------------------------
    # PDF VIEWER
    # --------------------------
    if st.session_state.viewing_pdf:
        st.markdown("---")
        st.subheader(f"📖 {st.session_state.viewing_pdf}")

        if st.button("Close Viewer"):
            st.session_state.viewing_pdf = None
            st.rerun()

        path = f"{user_id}/{st.session_state.viewing_pdf}"

        try:
            url = supabase.storage.from_("pdfs").get_public_url(path)["publicUrl"]

            st.markdown(
                f'<iframe src="{url}" width="100%" height="600"></iframe>',
                unsafe_allow_html=True
            )
        except Exception:
            st.error("Cannot load PDF")

    # --------------------------
    # CHAT
    # --------------------------
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    prompt = st.chat_input("Ask about your PDFs...")

    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):

                context = search_backend(prompt, user_id)

                llm = ChatGoogleGenerativeAI(
                    model="gemini-2.5-flash",
                    temperature=0.3,
                    google_api_key=st.secrets["GEMINI_API_KEY"]
                )

                template = PromptTemplate(
                    template="""
Answer ONLY from context.

Context:
{context}

Question:
{question}

Answer:
""",
                    input_variables=["context", "question"]
                )

                response = llm.invoke(
                    template.format(context=context, question=prompt)
                ).content

                st.markdown(response)

                st.session_state.messages.append({
                    "role": "assistant",
                    "content": response
                })
