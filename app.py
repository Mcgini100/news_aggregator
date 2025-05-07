from flask import Flask, render_template, request
import pandas as pd
import os
from datetime import datetime

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE_PATH = os.path.join(BASE_DIR, 'all_news_articles_with_clusters.csv')

def load_data():
    try:
        df = pd.read_csv(CSV_FILE_PATH)
        df['cluster_label_str'] = df['cluster_label'].astype(str) # For consistent filtering
        return df
    except FileNotFoundError:
        print(f"Error: The file {CSV_FILE_PATH} was not found. Make sure cluster_news.py has been run.")
        return pd.DataFrame()
    except Exception as e:
        print(f"Error loading data: {e}")
        return pd.DataFrame()

data_df = load_data()


def get_cluster_display_names(df):
    if df.empty or 'cluster_label' not in df.columns or 'category' not in df.columns:
        return {}

    cluster_names = {}
    # Filter out excluded items before determining names for actual clusters
    clustered_data = df[df['cluster_label'] != 'EXCLUDED_FROM_CLUSTERING']
    
    # Convert cluster_label to numeric if possible for grouping, handling potential errors
    try:
        # Attempt to convert to numeric, coercing errors to NaN, then dropna
        numeric_cluster_labels = pd.to_numeric(clustered_data['cluster_label'], errors='coerce').dropna().unique()
    except Exception: # Catch broader errors if conversion fails unexpectedly
        numeric_cluster_labels = clustered_data['cluster_label'].unique()


    for label in numeric_cluster_labels:
        if isinstance(label, (int, float)): # if the label from unique() is numeric
            stories_in_cluster = clustered_data[pd.to_numeric(clustered_data['cluster_label'], errors='coerce') == label]
        else: # if the label from unique() is already a string (should not happen for actual clusters now)
             stories_in_cluster = clustered_data[clustered_data['cluster_label'] == str(label)]


        if not stories_in_cluster.empty:
            # Get the most common original category for this cluster
            # In your case, it should be the only category
            most_common_category = stories_in_cluster['category'].mode()
            if not most_common_category.empty:
                cluster_names[str(int(label)) if isinstance(label, float) and label.is_integer() else str(label)] = most_common_category[0] # Use mode()[0]
            else:
                cluster_names[str(int(label)) if isinstance(label, float) and label.is_integer() else str(label)] = f"Cluster {label}" # Fallback
        else: # Should not happen if label comes from unique() on clustered_data
            cluster_names[str(int(label)) if isinstance(label, float) and label.is_integer() else str(label)] = f"Cluster {label} (empty)"

    if 'EXCLUDED_FROM_CLUSTERING' in df['cluster_label_str'].unique():
        cluster_names['EXCLUDED_FROM_CLUSTERING'] = "Articles Not Clustered (us_news)"
        
    return cluster_names


@app.route('/')
def index():
    if data_df.empty:
        return "Error: Could not load data. Please check the server logs and ensure 'all_news_articles_with_clusters.csv' exists."

    cluster_display_info = get_cluster_display_names(data_df)
    
    sorted_cluster_items = []
    excluded_item = None

    for cluster_id_str, display_name in cluster_display_info.items():
        if cluster_id_str == 'EXCLUDED_FROM_CLUSTERING':
            excluded_item = {'id_str': cluster_id_str, 'name': display_name}
        else:
            try:
                # Attempt to get a numeric key for sorting actual clusters
                numeric_key = int(float(cluster_id_str))
                sorted_cluster_items.append({'id_str': cluster_id_str, 'name': display_name, 'sort_key': numeric_key})
            except ValueError:
                 # If cluster_id_str is not purely numeric, use it as a string key (fallback)
                sorted_cluster_items.append({'id_str': cluster_id_str, 'name': display_name, 'sort_key': cluster_id_str})

    sorted_cluster_items.sort(key=lambda x: x['sort_key'])
    
   
    if excluded_item:
        sorted_cluster_items.append(excluded_item)
        
    current_year = datetime.now().year
    return render_template('index.html', cluster_items=sorted_cluster_items, now={'year': current_year})


@app.route('/cluster/<cluster_id_str>')
def cluster_details(cluster_id_str):
    if data_df.empty:
        return "Error: Could not load data."

    stories_in_cluster = data_df[data_df['cluster_label_str'] == cluster_id_str]
    
    cluster_names_map = get_cluster_display_names(data_df)
    display_title = cluster_names_map.get(cluster_id_str, f"Cluster {cluster_id_str}") # Fallback

    if stories_in_cluster.empty:
        return render_template('cluster_details.html', display_title=display_title, stories=[], message="No stories found for this cluster label.")

    stories_to_display = []
    for _, row in stories_in_cluster.iterrows():
        story_info = {
            'title': row.get('title', 'N/A'),
            'url': row.get('url', '#'),
            'summary': row.get('summary', ''),
            'source': row.get('source', '')
        }
        stories_to_display.append(story_info)
        
    current_year = datetime.now().year
    return render_template('cluster_details.html', display_title=display_title, stories=stories_to_display, now={'year': current_year})

#if __name__ == '__main__':
#    if data_df.empty:
#        print("Flask app will not run properly as data could not be loaded.")
#    else:
#        print("Data loaded successfully. Starting Flask app...")
#    app.run(debug=True)