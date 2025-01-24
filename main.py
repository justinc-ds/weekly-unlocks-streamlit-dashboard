import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
import requests
from time import sleep

st.set_page_config(
    page_title="Token Unlocks Dashboard",
    page_icon="📊",
    layout="wide"
)

@st.cache_data(ttl=3600)
def fetch_token_list(api_key):
    """Fetch list of all available tokens"""
    url = "https://api.unlocks.app/v1/token/list"
    headers = {"x-api-key": api_key}
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        st.error("Invalid API key. Please check your credentials.")
        return None
    return response.json().get("data")

@st.cache_data(ttl=3600)
def fetch_emission_data(token_id, api_key):
    """Fetch emission data for a token"""
    url = "https://api.unlocks.app/v2/emission"
    headers = {"x-api-key": api_key}
    params = {"tokenId": token_id}
    
    response = requests.get(url, headers=headers, params=params)
    if response.status_code != 200:
        return None
    return response.json().get("data")

@st.cache_data(ttl=3600)
def process_token_data(emission_data, token_symbol):
    """Process the API data into a DataFrame using weekly periods"""
    data = []
    
    for week in emission_data:
        start_date = datetime.strptime(week["startDate"], "%Y-%m-%dT%H:%M:%SZ")
        end_date = datetime.strptime(week["endDate"], "%Y-%m-%dT%H:%M:%SZ")
        
        week_id = f"{start_date.strftime('%Y-W%V')}"
        
        for allocation in week["allocations"]:
            unlock_amount = allocation["unlockAmount"]
            unlock_value_usd = allocation["unlockValue"]
            
            data.append({
                "token": token_symbol,
                "week": week_id,
                "start_date": start_date,
                "end_date": end_date,
                "amount": unlock_amount,
                "value_usd": unlock_value_usd,
            })
    
    return pd.DataFrame(data)

@st.cache_data(ttl=3600)  # Cache for 1 hour
def preprocess_data(data):
    """Group tokens with <5% of weekly total into 'OTHER'"""
    # Calculate total value and amount per week
    weekly_totals = data.groupby(['week', 'token']).agg({
        'value_usd': 'sum',
        'amount': 'sum'
    }).reset_index()
    
    week_sums = weekly_totals.groupby('week')['value_usd'].sum().reset_index()
    week_sums.columns = ['week', 'total_week_value']
    
    # Calculate percentages and identify tokens to group
    weekly_totals = weekly_totals.merge(week_sums, on='week')
    weekly_totals['percentage'] = (weekly_totals['value_usd'] / weekly_totals['total_week_value']) * 100
    weekly_totals['token'] = weekly_totals.apply(
        lambda x: 'OTHER' if x['percentage'] < 5 else x['token'],
        axis=1
    )
    
    # Reaggregate data with grouped tokens
    grouped_data = weekly_totals.groupby(['week', 'token']).agg({
        'value_usd': 'sum',
        'amount': 'sum'
    }).reset_index()
    
    # Merge back the dates
    dates_data = data[['week', 'start_date', 'end_date']].drop_duplicates()
    final_data = grouped_data.merge(dates_data, on='week')
    
    return final_data


@st.cache_data(ttl=3600)
def load_selected_data(api_key, selected_tokens, token_map):
    """Load and process data for selected tokens"""
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    all_data = []
    total_tokens = len(selected_tokens)
    
    for i, token_symbol in enumerate(selected_tokens):
        token_id = token_map[token_symbol]
        status_text.text(f"Processing {token_symbol}...")
        
        try:
            emission_data = fetch_emission_data(token_id, api_key)
            if emission_data:
                token_data = process_token_data(emission_data, token_symbol)
                all_data.append(token_data)
        except Exception as e:
            st.warning(f"Error processing {token_symbol}")
            continue
            
        progress_bar.progress((i + 1) / total_tokens)
        sleep(0.3)
    
    status_text.empty()
    progress_bar.empty()
    
    if not all_data:
        st.error("No data was loaded. Please check your selections and try again.")
        return None
        
    combined_data = pd.concat(all_data, ignore_index=True)
    return preprocess_data(combined_data)

def main():
    st.title("📊 Token Unlocks Dashboard")
    
    # Sidebar for API key input and token selection
    with st.sidebar:
        st.header("Configuration")
        api_key = st.text_input("Enter your API key", type="password")

        if api_key:
            # Fetch token list
            tokens = fetch_token_list(api_key)
            if tokens is not None:
                # Create token map and list
                token_map = {token["symbol"]: token["id"] for token in tokens}
                token_list = list(token_map.keys())
                
                # Token selection
                st.subheader("Select Tokens")
                all_selected = st.checkbox("Select All")
                if all_selected:
                    selected_tokens = token_list
                else:
                    selected_tokens = st.multiselect(
                        "Choose tokens to analyze",
                        options=token_list,
                        default=token_list[:5]  # Default to first 5 tokens
                    )
                
                # Generate button
                if st.button("Generate Dashboard", disabled=len(selected_tokens) == 0):
                    st.session_state.data = load_selected_data(api_key, selected_tokens, token_map)
    
    if not api_key:
        st.info("Please enter your API key in the sidebar to begin.")
        return
    
    if 'data' not in st.session_state or st.session_state.data is None:
        return
    
    data = st.session_state.data
    
    # Date range selector
    st.markdown("### Select Date Range")
    col1, col2 = st.columns(2)
    
    with col1:
        start_date = st.date_input(
            "Start Date",
            min_value=data['start_date'].min().date(),
            max_value=data['end_date'].max().date(),
            value=data['start_date'].min().date()
        )
    
    with col2:
        end_date = st.date_input(
            "End Date",
            min_value=data['start_date'].min().date(),
            max_value=data['end_date'].max().date(),
            value=data['end_date'].max().date()
        )
    
    # Filter data by date range
    filtered_data = data[
        (data['start_date'].dt.date >= start_date) & 
        (data['end_date'].dt.date <= end_date)
    ]
    
    if filtered_data.empty:
        st.warning("No data available for the selected date range.")
        return
    
    # Display metrics
    st.markdown("### Key Metrics")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        total_value = filtered_data['value_usd'].sum()
        st.metric("Total Value", f"${total_value:,.0f}")
    
    with col2:
        non_other_tokens = len([t for t in filtered_data['token'].unique() if t != 'OTHER'])
        st.metric("Significant Tokens", non_other_tokens)
    
    with col3:
        avg_weekly_value = filtered_data.groupby('week')['value_usd'].sum().mean()
        st.metric("Average Weekly Value", f"${avg_weekly_value:,.0f}")
    
    # Create stacked bar chart with enhanced hover
    st.markdown("### Weekly Token Unlocks")
    
    # Prepare hover text
    filtered_data['hover_text'] = filtered_data.apply(
        lambda row: f"Token: {row['token']}<br>" +
                   f"Value: ${row['value_usd']:,.0f}<br>" +
                   f"Amount: {row['amount']:,.2f}<br>" +
                   f"Week Start: {row['start_date'].strftime('%Y-%m-%d')}<br>" +
                   f"Week End: {row['end_date'].strftime('%Y-%m-%d')}",
        axis=1
    )
    
    fig = px.bar(
        filtered_data,
        x='week',
        y='value_usd',
        color='token',
        title='Token Unlocks by Week',
        labels={'value_usd': 'Value (USD)', 'week': 'Week'},
        height=600,
        custom_data=['hover_text']  # Include custom hover data
    )
    
    # Update hover template
    fig.update_traces(
        hovertemplate="%{customdata[0]}<extra></extra>"
    )
    
    fig.update_layout(
        barmode='stack',
        xaxis_tickangle=-45,
        legend_title="Tokens",
        legend={'yanchor': "top", 'y': 0.99, 'xanchor': "left", 'x': 1.01},
        showlegend=True
    )
    
    fig.update_yaxes(
        title_text="Value (USD)",
        tickformat="$,.0f"
    )
    
    st.plotly_chart(fig, use_container_width=True)

if __name__ == "__main__":
    main()