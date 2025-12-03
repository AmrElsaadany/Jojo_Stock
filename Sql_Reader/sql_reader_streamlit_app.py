# sql_reader_streamlit_app.py
import streamlit as st
import pandas as pd
import sqlite3
import os
from pathlib import Path
from datetime import datetime

# Set page configuration
st.set_page_config(
    page_title="SQL File Reader",
    page_icon="🗄️",
    layout="wide",
    initial_sidebar_state="expanded"
)

def read_sql_file(file_path):
    """Read SQL file and return its content"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        st.error(f"Error reading SQL file: {e}")
        return None

def list_sql_files(directory="."):
    """List all .sql files in a directory"""
    try:
        sql_files = list(Path(directory).glob("*.sql"))
        return sorted([str(f) for f in sql_files])
    except Exception as e:
        st.error(f"Error listing SQL files: {e}")
        return []

def execute_query(db_path, query):
    """Execute SQL query on SQLite database"""
    try:
        conn = sqlite3.connect(db_path)
        df = pd.read_sql_query(query, conn)
        conn.close()
        return df
    except Exception as e:
        st.error(f"Error executing query: {e}")
        return None

def create_sample_database():
    """Create a sample SQLite database for demonstration"""
    db_path = "sample.db"
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Create sample tables
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                price REAL,
                category TEXT,
                stock INTEGER
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY,
                product_id INTEGER,
                quantity INTEGER,
                sale_date DATE,
                FOREIGN KEY (product_id) REFERENCES products(id)
            )
        ''')
        
        # Insert sample data
        cursor.execute("DELETE FROM products")
        cursor.execute("DELETE FROM sales")
        
        products = [
            (1, 'Laptop', 999.99, 'Electronics', 15),
            (2, 'Mouse', 29.99, 'Electronics', 50),
            (3, 'Keyboard', 79.99, 'Electronics', 30),
            (4, 'Monitor', 299.99, 'Electronics', 20),
            (5, 'Desk', 199.99, 'Furniture', 10),
        ]
        cursor.executemany(
            "INSERT INTO products (id, name, price, category, stock) VALUES (?, ?, ?, ?, ?)",
            products
        )
        
        sales = [
            (1, 1, 2, '2025-11-15'),
            (2, 2, 5, '2025-11-16'),
            (3, 3, 3, '2025-11-17'),
            (4, 1, 1, '2025-11-18'),
            (5, 4, 2, '2025-11-18'),
        ]
        cursor.executemany(
            "INSERT INTO sales (id, product_id, quantity, sale_date) VALUES (?, ?, ?, ?)",
            sales
        )
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Error creating sample database: {e}")
        return False

def main():
    st.title("🗄️ SQL File Reader")
    st.markdown("Read and execute SQL files with ease using Streamlit")
    
    with st.sidebar:
        st.header("Configuration")
        
        # Database selection
        st.subheader("Database Connection")
        db_type = st.radio("Select Database Type:", ["SQLite", "Upload SQL File"])
        
        if db_type == "SQLite":
            db_path = st.text_input(
                "SQLite Database Path:",
                value="sample.db",
                placeholder="e.g., sample.db"
            )
            
            # Create sample database button
            if st.button("📊 Create Sample Database", use_container_width=True):
                if create_sample_database():
                    st.success("Sample database created successfully!")
                    st.rerun()
        
        st.markdown("---")
        st.subheader("SQL File Selection")
        sql_source = st.radio(
            "SQL Source:",
            ["From Directory", "Upload File", "Write Query"]
        )
    
    # Main content area
    if db_type == "SQLite":
        if sql_source == "From Directory":
            st.header("📂 Load SQL from Directory")
            
            directory = st.text_input(
                "Directory path:",
                value=".",
                placeholder="Enter directory containing .sql files"
            )
            
            sql_files = list_sql_files(directory)
            
            if sql_files:
                selected_file = st.selectbox(
                    "Select SQL file:",
                    sql_files,
                    format_func=lambda x: Path(x).name
                )
                
                # Read and display SQL file
                sql_content = read_sql_file(selected_file)
                
                if sql_content:
                    st.subheader(f"📋 File: {Path(selected_file).name}")
                    
                    # Display SQL code
                    with st.expander("View SQL Code", expanded=True):
                        st.code(sql_content, language="sql")
                    
                    # Execute button
                    col1, col2 = st.columns([1, 1])
                    with col1:
                        if st.button("▶️ Execute Query", type="primary", use_container_width=True):
                            if os.path.exists(db_path):
                                result_df = execute_query(db_path, sql_content)
                                
                                if result_df is not None:
                                    st.success("✅ Query executed successfully!")
                                    st.dataframe(result_df, use_container_width=True)
                                    
                                    # Download option
                                    csv = result_df.to_csv(index=False)
                                    st.download_button(
                                        label="📥 Download Results as CSV",
                                        data=csv,
                                        file_name=f"query_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                                        mime="text/csv"
                                    )
                            else:
                                st.error(f"Database file '{db_path}' not found!")
                    
                    with col2:
                        if st.button("📋 Copy SQL", use_container_width=True):
                            st.write(sql_content)
            else:
                st.info(f"No .sql files found in '{directory}'")
        
        elif sql_source == "Upload File":
            st.header("📤 Upload SQL File")
            
            uploaded_file = st.file_uploader(
                "Choose a SQL file",
                type=["sql"],
                help="Upload a .sql file to execute"
            )
            
            if uploaded_file is not None:
                sql_content = uploaded_file.read().decode("utf-8")
                
                st.subheader(f"📋 File: {uploaded_file.name}")
                
                with st.expander("View SQL Code", expanded=True):
                    st.code(sql_content, language="sql")
                
                if st.button("▶️ Execute Query", type="primary", use_container_width=True):
                    if os.path.exists(db_path):
                        result_df = execute_query(db_path, sql_content)
                        
                        if result_df is not None:
                            st.success("✅ Query executed successfully!")
                            st.dataframe(result_df, use_container_width=True)
                            
                            csv = result_df.to_csv(index=False)
                            st.download_button(
                                label="📥 Download Results as CSV",
                                data=csv,
                                file_name=f"query_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                                mime="text/csv"
                            )
                    else:
                        st.error(f"Database file '{db_path}' not found!")
        
        elif sql_source == "Write Query":
            st.header("✍️ Write SQL Query")
            
            # Query editor
            sql_query = st.text_area(
                "Enter SQL query:",
                height=200,
                placeholder="SELECT * FROM products;",
                help="Write your SQL query here"
            )
            
            if sql_query:
                with st.expander("Query Preview", expanded=False):
                    st.code(sql_query, language="sql")
                
                if st.button("▶️ Execute Query", type="primary", use_container_width=True):
                    if os.path.exists(db_path):
                        result_df = execute_query(db_path, sql_query)
                        
                        if result_df is not None:
                            st.success("✅ Query executed successfully!")
                            st.dataframe(result_df, use_container_width=True)
                            
                            # Show statistics
                            col1, col2, col3 = st.columns(3)
                            with col1:
                                st.metric("Rows", len(result_df))
                            with col2:
                                st.metric("Columns", len(result_df.columns))
                            with col3:
                                st.metric("Size", f"{result_df.memory_usage(deep=True).sum() / 1024:.2f} KB")
                            
                            csv = result_df.to_csv(index=False)
                            st.download_button(
                                label="📥 Download Results as CSV",
                                data=csv,
                                file_name=f"query_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                                mime="text/csv"
                            )
                    else:
                        st.error(f"Database file '{db_path}' not found!")
    
    # Footer
    st.markdown("---")
    st.markdown("*SQL File Reader - Powered by Streamlit*")

if __name__ == "__main__":
    main()
