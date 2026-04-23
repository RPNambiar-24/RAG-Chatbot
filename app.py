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
# SUPABASE CLIENT
# ==============================
def get_supabase_client() -> Client:
    client = create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_KEY"]
    )

    if "session" in st.session_state:
        try:
            client.auth.set_session(
                st.session_state.session["access_token"],
                st.session_state.session["refresh_token"]
            )
        except:
            pass

    return client

supabase = get_supabase_client()

# ==============================
# SESSION STATE
# ==============================
if "user" not in st.session_state:
    st.session_state.user = None

if "messages" not in st.session_state:
    st.session_state.messages = []

if "viewing_pdf" not in st.session_state:
    st.session_state.viewing_pdf = None


# ==============================
# AUTH
# ==============================
def auth_flow():
    st.sidebar.title("Authentication")

    if st.session_state.user:
        st.sidebar.write(f"Logged in as: {st.session_state.user.email}")

        if st.sidebar.button("Logout"):
            supabase.auth.sign_out()
            st.session_state.user = None
            st.session_state.session = None
            st.rerun()

        return True

    tab1, tab2 = st.sidebar.tabs(["Login", "Signup"])

    with tab1:
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")

        if st.button("Login"):
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

    with tab2:
        email = st.text_input("Email", key="signup_email")
        password = st.text_input("Password", type="password", key="signup_pass")

        if st.button("Sign Up"):
            supabase.auth.sign_up({
                "email": email,
                "password": password
            })
            st.success("Signup successful")

    return False


# ==============================
# STORAGE
# ==============================
def upload_file(file, user_id):
    path = f"{user_id}/{file.name}"
    supabase.storage.from_("pdfs").upload(
        path,
        file.getvalue(),
        file_options={"content-type": "application/pdf"}
    )
    return path


# ==============================
# BACKEND
# ==============================
def process_pdf(file, user_id):
    return requests.post(
        f"{BACKEND_URL}/process_pdf",
        files={"file": (file.name, file.getvalue(), "application/pdf")},
        data={"user_id": user_id}
    ).json()


def search(query, user_id):
    res = requests.post(
        f"{BACKEND_URL}/search",
        json={"query": query, "user_id": user_id}
    )
    return res.json().get("context", "")


# ==============================
# MAIN
# ==============================
if auth_flow():

    st.title("📄 RAG Chatbot")
    user_id = st.session_state.user.id

    # --------------------------
    # UPLOAD
    # --------------------------
    uploaded_files = st.file_uploader(
        "Upload PDFs", type=["pdf"], accept_multiple_files=True
    )

    if uploaded_files and st.button("Process Documents"):
        existing = [
            f["name"] for f in supabase.storage.from_("pdfs").list(user_id)
        ]

        for file in uploaded_files:
            if file.name in existing:
                st.warning(f"{file.name} already exists")
                continue

            st.info(f"Processing {file.name}...")

            upload_file(file, user_id)
            process_pdf(file, user_id)

            st.success(f"{file.name} processed successfully")

    # --------------------------
    # DOCUMENTS
    # --------------------------
    st.sidebar.subheader("📚 Documents")

    files = supabase.storage.from_("pdfs").list(user_id)
    docs = [f["name"] for f in files] if files else []

    for doc in docs:
        col1, col2 = st.sidebar.columns([8, 2])

        with col1:
            if st.button(doc, key=f"view_{doc}"):
                st.session_state.viewing_pdf = doc

        with col2:
            if st.button("❌", key=f"del_{doc}"):
                requests.post(
                    f"{BACKEND_URL}/delete_pdf",
                    json={"file_name": doc, "user_id": user_id}
                )
                supabase.storage.from_("pdfs").remove([f"{user_id}/{doc}"])
                st.rerun()

    # --------------------------
    # VIEWER
    # --------------------------
    if st.session_state.viewing_pdf:
        path = f"{user_id}/{st.session_state.viewing_pdf}"
        url = supabase.storage.from_("pdfs").get_public_url(path)["publicUrl"]

        st.markdown(
            f'<iframe src="{url}" width="100%" height="600"></iframe>',
            unsafe_allow_html=True
        )

    # --------------------------
    # CHAT
    # --------------------------
    if st.button("🧹 Clear Chat"):
        st.session_state.messages = []
        st.rerun()

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    prompt = st.chat_input("Ask something...")

    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})

        context = search(prompt, user_id)

        if not context or "No relevant context" in context:
            st.warning("No relevant info found. Upload documents first.")
            st.session_state.messages.append({
                "role": "assistant",
                "content": "No relevant information found."
            })
        else:
            llm = ChatGoogleGenerativeAI(
                model="gemini-2.5-flash",
                temperature=0.3,
                google_api_key=st.secrets["GEMINI_API_KEY"]
            )

            prompt_template = PromptTemplate(
                template="Context:\n{context}\n\nQuestion:\n{question}\nAnswer:",
                input_variables=["context", "question"]
            )

            response = llm.invoke(
                prompt_template.format(context=context, question=prompt)
            ).content

            st.chat_message("assistant").markdown(response)

            st.session_state.messages.append({
                "role": "assistant",
                "content": response
            })
