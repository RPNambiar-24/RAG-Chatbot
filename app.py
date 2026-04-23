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
    return res.json()


# ==============================
# MAIN
# ==============================
if auth_flow():

    st.title("📄 RAG Chatbot")

    user_id = st.session_state.user.id

    # --------------------------
    # CHAT CLEAR
    # --------------------------
    if st.button("🧹 Clear Chat"):
        st.session_state.messages = []
        st.rerun()

    # --------------------------
    # RENDER HISTORY
    # --------------------------
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

            # Show sources if exist
            if "sources" in msg:
                st.markdown("**Sources:**")
                for s in msg["sources"]:
                    st.markdown(f"- {s}")

    # --------------------------
    # INPUT
    # --------------------------
    prompt = st.chat_input("Ask something...")

    if prompt:
        # SHOW USER MESSAGE IMMEDIATELY
        with st.chat_message("user"):
            st.markdown(prompt)

        st.session_state.messages.append({
            "role": "user",
            "content": prompt
        })

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):

                result = search(prompt, user_id)
                context = result.get("context", "")
                sources = result.get("sources", [])

                # HANDLE EMPTY CONTEXT
                if not context or "No relevant context" in context:
                    response_text = "No relevant information found. Upload documents first."
                    st.warning(response_text)

                else:
                    llm = ChatGoogleGenerativeAI(
                        model="gemini-2.5-flash",
                        temperature=0.3,
                        google_api_key=st.secrets["GEMINI_API_KEY"]
                    )

                    prompt_template = PromptTemplate(
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

                    response_text = llm.invoke(
                        prompt_template.format(
                            context=context,
                            question=prompt
                        )
                    ).content

                    st.markdown(response_text)

                    # SHOW SOURCES
                    if sources:
                        st.markdown("**Sources:**")
                        for s in sources:
                            st.markdown(f"- {s}")

        # STORE MESSAGE WITH SOURCES
        st.session_state.messages.append({
            "role": "assistant",
            "content": response_text,
            "sources": sources
        })
