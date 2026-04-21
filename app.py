import streamlit as st
import asyncio
import os
import sys
from supabase import create_client, Client
from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate
import base64

if "viewing_pdf" not in st.session_state:
        st.session_state.viewing_pdf = None


# --- 1. SUPABASE AUTH SETUP ---
@st.cache_resource
def init_supabase() -> Client:
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

supabase = init_supabase()

if "user" not in st.session_state:
    st.session_state.user = None

def auth_flow():
    st.sidebar.title("Authentication")
    if st.session_state.user:
        st.sidebar.write(f"Logged in as: **{st.session_state.user.email}**")
        if st.sidebar.button("Log Out"):
            supabase.auth.sign_out()
            st.session_state.user = None
            st.rerun()
        return True
    else:
        tab1, tab2 = st.sidebar.tabs(["Log In", "Sign Up"])
        with tab1:
            email = st.text_input("Email", key="log_email")
            password = st.text_input("Password", type="password", key="log_pass")
            if st.button("Log In"):
                try:
                    res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                    st.session_state.user = res.user
                    st.rerun()
                except Exception as e:
                    st.sidebar.error(f"Login failed: {e}")
        with tab2:
            email_up = st.text_input("Email", key="up_email")
            password_up = st.text_input("Password", type="password", key="up_pass")
            if st.button("Sign Up"):
                try:
                    supabase.auth.sign_up({"email": email_up, "password": password_up})
                    st.sidebar.success("Registration successful! You can now log in.")
                except Exception as e:
                    st.sidebar.error(f"Registration failed: {e}")
        return False

# --- 2. MCP CLIENT COMMUNICATION ---
async def run_mcp_tool(tool_name: str, arguments: dict):
    """Connects to the local server.py using the Model Context Protocol."""
    
    # Update this line to use sys.executable
    server_params = StdioServerParameters(
        command=sys.executable, 
        args=["server.py"]
    )
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            return result.content[0].text

# --- POP-UP MODALS ---
@st.dialog("Delete Document")
def delete_file_popup(file_name, file_path, user_id):
    st.write(f"Are you sure you want to permanently delete **{file_name}**?")
    st.write("This will remove it from your library and the chatbot's memory.")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Cancel", use_container_width=True):
            st.rerun() # Closes the modal without doing anything
            
    with col2:
        # Use type="primary" to make the delete button stand out (red/accent color)
        # INSIDE your delete_file_popup function in app.py:
        if st.button("Yes, Delete", type="primary", use_container_width=True):
            with st.spinner("Deleting..."):
                # Pass file_name to the MCP server instead of file_path
                asyncio.run(run_mcp_tool("delete_pdf", {
                    "file_name": file_name,  # <--- Change this line
                    "user_id": user_id
                }))
                
                # Keep the rest exactly the same...
                if os.path.exists(file_path):
                    os.remove(file_path)
                    
                # 3. If the user was actively reading this PDF, close the viewer
                if st.session_state.viewing_pdf == file_name:
                    st.session_state.viewing_pdf = None
                    
                # Refresh the UI and close the popup
                st.rerun()


@st.dialog("Delete All Documents")
def delete_all_popup(user_id, user_folder):
    st.error("⚠️ Are you sure you want to permanently delete **ALL** documents?")
    st.write("This will wipe your entire library and clear the chatbot's memory.")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Cancel", use_container_width=True):
            st.rerun()
            
    with col2:
        if st.button("Yes, Delete Everything", type="primary", use_container_width=True):
            with st.spinner("Deleting entire library..."):
                # 1. Ask MCP Server to wipe all this user's data from ChromaDB
                asyncio.run(run_mcp_tool("delete_all_pdfs", {
                    "user_id": user_id
                }))
                
                # 2. Delete all physical PDFs from the hard drive loop
                if os.path.exists(user_folder):
                    for file in os.listdir(user_folder):
                        os.remove(os.path.join(user_folder, file))
                        
                # 3. Close the viewer if they were looking at something
                st.session_state.viewing_pdf = None
                
                # Refresh the UI
                st.rerun()
# --- 3. MAIN UI & RAG LOGIC ---
st.set_page_config(page_title="MCP RAG Chatbot", layout="wide")

if auth_flow():
    st.title("RAG Chatbot")
    user_id = st.session_state.user.id

    # File Uploading
    # --- File Uploading & Permanent Storage ---
    # 1. Create a main directory for all user data if it doesn't exist
    BASE_STORAGE_DIR = "saved_user_pdfs"
    os.makedirs(BASE_STORAGE_DIR, exist_ok=True)
    
    # 2. Create a specific sub-folder just for the logged-in user
    user_folder = os.path.join(BASE_STORAGE_DIR, user_id)
    os.makedirs(user_folder, exist_ok=True)

    uploaded_files = st.file_uploader("Upload PDFs", type=["pdf"], accept_multiple_files=True)
    
    if uploaded_files and st.button("Process Documents"):
        with st.spinner(f"Processing {len(uploaded_files)} documents..."):
            for uploaded_file in uploaded_files:
                
                # 3. Save the file permanently into the user's specific folder
                save_path = os.path.join(user_folder, uploaded_file.name)
                with open(save_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                
                # 4. Pass that permanent path to the MCP server
                asyncio.run(run_mcp_tool("process_pdf", {
                    "file_path": save_path, 
                    "user_id": user_id
                }))
                
                # Notice: We removed os.remove() so the file stays forever!
                
            st.success(f"Successfully processed and saved {len(uploaded_files)} document(s)!")
            st.success(f"Success! Processed and saved {len(uploaded_files)} document(s) to the database.")
# --- PDF Viewer Display ---
    if st.session_state.viewing_pdf:
        # Create an expander that is open by default when a file is clicked
        with st.expander(f"📖 Reading: {st.session_state.viewing_pdf}", expanded=True):
            
            # Add a button to close the viewer
            if st.button("Close Viewer"):
                st.session_state.viewing_pdf = None
                st.rerun()
                
            # If the user hasn't closed it, render the PDF
            if st.session_state.viewing_pdf:
                pdf_path = os.path.join(user_folder, st.session_state.viewing_pdf)
                
                # Read the file and encode it
                with open(pdf_path, "rb") as f:
                    base64_pdf = base64.b64encode(f.read()).decode('utf-8')
                
                # Embed it in the app using an HTML iframe
                pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="600" type="application/pdf"></iframe>'
                st.markdown(pdf_display, unsafe_allow_html=True)
    # Chat Interface
    if "messages" not in st.session_state:
        st.session_state.messages = []

    
    # 1. ADD THIS: A layout with a title and a clear button aligned to the right
    col1, col2 = st.columns([8, 2])
    with col1:
        st.subheader("Conversation")
    with col2:
        if st.button("🗑️ Clear Chat", use_container_width=True):
            st.session_state.messages = []
            st.rerun() # Immediately refreshes the UI to wipe the screen

    # 2. Display existing messages
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Ask a question about your documents..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    # 1. Ask MCP Server to search ChromaDB (now includes filenames)
                    context = asyncio.run(run_mcp_tool("search_pdfs", {
                        "query": prompt, 
                        "user_id": user_id
                    }))

                    llm = ChatGoogleGenerativeAI(
                        model="gemini-2.5-flash", 
                        temperature=0.3, 
                        google_api_key=st.secrets["GEMINI_API_KEY"],
                        max_retries=3
                    )
                    
                    # 2. Update the Prompt to mandate citations
                    qa_prompt = PromptTemplate(
                        template="""You are a precise data assistant. Answer the user's question using ONLY the provided context. 
                        
                        You MUST format your final response exactly like this:
                        
                        [Write your detailed answer here. Cite the source file name in your text.]
                        
                        ---
                        **🔍 Exact Quote Used:**
                        > "[Copy and paste the exact sentence or paragraph from the context that proves your answer]"
                        *(Source: [Insert Source Name])*
                        
                        Context:
                        {context}
                        
                        Question: {question}
                        
                        Answer:""",
                        input_variables=["context", "question"]
                    )
                    
                    final_answer = llm.invoke(qa_prompt.format(context=context, question=prompt)).content
                    
                    # 3. Display the Answer
                    st.markdown(final_answer)
                    
                    # 5. Save to history
                    st.session_state.messages.append({"role": "assistant", "content": final_answer})
                    
                except Exception as e:
                    if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                        st.warning("⏳ Google Gemini's Free Tier speed limit reached. Please wait about 60 seconds and try again!")
                    else:
                        st.error(f"Something went wrong: {str(e)}")

# --- Sidebar: User's Document Library ---
    st.sidebar.markdown("---")
    st.sidebar.subheader("📚 Your Document Library")
    
    user_folder = os.path.join("saved_user_pdfs", user_id)

    if os.path.exists(user_folder):
        user_files = os.listdir(user_folder)
        if user_files:
            if st.sidebar.button("🗑️ Delete All PDFs", type="primary", use_container_width=True):
                delete_all_popup(user_id, user_folder)
                
            st.sidebar.markdown("---")
            for file_name in user_files:
                # Use Streamlit columns to put the View and Delete buttons side-by-side
                col1, col2 = st.sidebar.columns([8, 2])
                
                with col1:
                    # View Button
                    if st.button(f"📄 {file_name}", key=f"view_{file_name}", use_container_width=True):
                        st.session_state.viewing_pdf = file_name
                        
                with col2:
                    # Delete Button triggers the Pop-up
                    if st.button("❌", key=f"del_{file_name}"):
                        file_path = os.path.join(user_folder, file_name)
                        
                        # Call the pop-up function we just created
                        delete_file_popup(file_name, file_path, user_id)
        else:
            st.sidebar.info("Your library is empty.")
    else:
        st.sidebar.info("Your library is empty.")