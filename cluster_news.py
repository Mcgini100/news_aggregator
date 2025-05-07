# cluster_news.py

import pandas as pd
import os
import glob
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score, davies_bouldin_score, calinski_harabasz_score
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score
from sklearn.metrics import homogeneity_score, completeness_score, v_measure_score
from collections import Counter
import joblib

# Define the path to the data directory relative to this script
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'scraped_data')
MODELS_DIR = os.path.join(BASE_DIR, 'saved_models') # Directory to save models
CATEGORY_TO_EXCLUDE = 'us_news'

# Ensure models directory exists
os.makedirs(MODELS_DIR, exist_ok=True)

def load_all_data(data_dir):
    """Loads all CSV files from the specified directory into a single DataFrame."""
    all_files = glob.glob(os.path.join(data_dir, "*.csv"))
    if not all_files:
        print(f"No CSV files found in {data_dir}")
        return pd.DataFrame()

    df_list = []
    # print(f"Found {len(all_files)} CSV files to process.") # Printed in main
    for filename in all_files:
        try:
            df = pd.read_csv(filename)
            if df.empty:
                print(f"Warning: {filename} is empty and will be skipped.")
                continue
            df_list.append(df)
        except pd.errors.EmptyDataError:
            print(f"Warning: {filename} is empty and will be skipped (pd.errors.EmptyDataError).")
        except Exception as e:
            print(f"Warning: Could not read {filename} due to {e}. Skipping.")

    if not df_list:
        print("No data loaded from CSV files.")
        return pd.DataFrame()

    combined_df = pd.concat(df_list, ignore_index=True)
    return combined_df


def main():
    # 1. Load data
    print(f"Loading data from: {DATA_DIR}")
    df_all = load_all_data(DATA_DIR)

    if df_all.empty:
        print("Exiting: No data to process.")
        return

    print(f"\nSuccessfully loaded {len(df_all)} articles initially.")
    
    if 'category' not in df_all.columns:
        print("Error: 'category' column not found in the loaded DataFrame.")
        return
        
    # Filter out the specified category
    df_all['category_lower'] = df_all['category'].fillna('').astype(str).str.lower()
    df = df_all[df_all['category_lower'] != CATEGORY_TO_EXCLUDE.lower()].copy()
    
    num_excluded = len(df_all) - len(df)
    if num_excluded > 0:
        print(f"\nExcluded {num_excluded} articles with category '{CATEGORY_TO_EXCLUDE}'.")
    print(f"Proceeding with {len(df)} articles for clustering.")

    if df.empty:
        print(f"Exiting: No data left to process after excluding '{CATEGORY_TO_EXCLUDE}'.")
        return

    # Prepare original labels for extrinsic evaluation
    df['category_for_clustering'] = df['category'].fillna('Unknown').astype(str)
    true_labels = df['category_for_clustering'] 

    print("\nUnique categories identified for clustering:", true_labels.nunique())
    value_counts_str = "\n".join([f"  {cat}: {count}" for cat, count in true_labels.value_counts().items()])
    print(f"Category distribution (after excluding):\n{value_counts_str}")


    # 2. Preprocessing and Feature Engineering for 'category_for_clustering'
    vectorizer = TfidfVectorizer(stop_words='english', lowercase=True, min_df=1)
    
    if true_labels.empty:
        print("No categories available for vectorization. Exiting.")
        return
        
    X = vectorizer.fit_transform(true_labels) # Vectorize the text of the categories themselves

    # 3. Determine the number of clusters
    num_unique_categories = true_labels.nunique()
    
    if num_unique_categories == 0:
        print("No unique categories found to form clusters. Exiting.")
        return
    
    if num_unique_categories < 2:
        n_clusters = num_unique_categories 
    elif X.shape[0] <= num_unique_categories and X.shape[0] > 1: # If num samples is less than unique categories (but > 1)
         print(f"Warning: Number of samples ({X.shape[0]}) is less than or equal to unique categories for clustering ({num_unique_categories}).")
         print(f"Adjusting n_clusters to {max(1, X.shape[0] -1)} for metric calculation.")
         n_clusters = max(1, X.shape[0] -1 ) # Must be at least 1, and less than n_samples for some metrics
    else:
        n_clusters = num_unique_categories

    if n_clusters == 0 : # Should be caught by num_unique_categories == 0
        print("n_clusters is 0, cannot proceed.")
        return
    if X.shape[0] < 2 and n_clusters >= X.shape[0]: 
        print(f"Very few samples ({X.shape[0]}). Clustering metrics might not be meaningful or computable.")
        if X.shape[0] == 1 and n_clusters > 1:
            n_clusters = 1

    print(f"\nSetting number of clusters (K) to: {n_clusters}")

    # 4. Apply K-Means clustering
    if X.shape[0] == 0:
        print("No data to cluster after vectorization. Exiting.")
        return
    
    if n_clusters > X.shape[0]:
        print(f"Error: n_clusters ({n_clusters}) cannot be greater than n_samples ({X.shape[0]}). Adjusting.")
        n_clusters = X.shape[0]
        if n_clusters < 1: 
            print("No samples to cluster.")
            return

    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init='auto')
    
    try:
        cluster_assignments = kmeans.fit_predict(X)
        df['cluster_label'] = cluster_assignments
    except ValueError as e:
        print(f"Error during K-Means fitting: {e}")
        print(f"Details: X.shape={X.shape}, n_clusters={n_clusters}")
        return

    # 5. Evaluate Clustering Quality
    print("\n--- Clustering Quality Metrics ---")
    print(f"K-Means Inertia (Within-cluster sum-of-squares): {kmeans.inertia_:.2f} (Lower is better)")

    can_compute_intrinsic_metrics = (n_clusters > 1 and X.shape[0] > n_clusters)

    if can_compute_intrinsic_metrics:
        try:
            silhouette_avg = silhouette_score(X, cluster_assignments)
            print(f"Silhouette Score: {silhouette_avg:.2f} (Range: -1 to 1, higher is better)")
        except ValueError as e:
            print(f"Could not compute Silhouette Score: {e}")

        try:
            # Davies-Bouldin and Calinski-Harabasz prefer dense arrays
            X_dense = X.toarray() if hasattr(X, "toarray") else X
            db_score = davies_bouldin_score(X_dense, cluster_assignments)
            print(f"Davies-Bouldin Index: {db_score:.2f} (Lower is better, closer to 0)")
        except ValueError as e:
            print(f"Could not compute Davies-Bouldin Index: {e}")
        
        try:
            X_dense = X.toarray() if hasattr(X, "toarray") else X
            ch_score = calinski_harabasz_score(X_dense, cluster_assignments)
            print(f"Calinski-Harabasz Index: {ch_score:.2f} (Higher is better)")
        except ValueError as e:
            print(f"Could not compute Calinski-Harabasz Index: {e}")
    else:
        print("Skipping Silhouette, Davies-Bouldin, Calinski-Harabasz scores (requires n_clusters > 1 and n_samples > n_clusters).")

    if not true_labels.empty and len(cluster_assignments) == len(true_labels):
        print(f"\n--- Extrinsic Evaluation (vs. Original Categories) ---")
        print(f"Adjusted Rand Index (ARI): {adjusted_rand_score(true_labels, cluster_assignments):.2f}")
        print(f"Normalized Mutual Information (NMI): {normalized_mutual_info_score(true_labels, cluster_assignments):.2f}")
        print(f"Homogeneity Score: {homogeneity_score(true_labels, cluster_assignments):.2f}")
        print(f"Completeness Score: {completeness_score(true_labels, cluster_assignments):.2f}")
        print(f"V-measure: {v_measure_score(true_labels, cluster_assignments):.2f}")
    else:
        print("Skipping extrinsic evaluation metrics (true_labels or cluster_assignments are problematic).")


    # 6. Qualitative Cluster Content Analysis
    print("\n--- Qualitative Cluster Content Analysis (for clustered data) ---")
    unique_assigned_clusters = sorted(df['cluster_label'].unique())
    for cluster_num in unique_assigned_clusters:
        cluster_data = df[df['cluster_label'] == cluster_num]
        if not cluster_data.empty:
            original_category_counts = cluster_data['category'].fillna('Original_Unknown').value_counts()
            most_common_original_category = original_category_counts.index[0]
            print(f"\nCluster {cluster_num}: Num articles: {len(cluster_data)}, Most common original category: '{most_common_original_category}' ({original_category_counts.iloc[0]})")
        else:
            print(f"\nCluster {cluster_num}: Found to be empty in DataFrame (unexpected).")


    # 7. Merge cluster labels back and save the DataFrame
    df_all = df_all.merge(df[['cluster_label']], left_index=True, right_index=True, how='left')
    df_all['cluster_label'] = df_all['cluster_label'].fillna('EXCLUDED_FROM_CLUSTERING')

    # --- FIX FOR CLUSTER LABEL FORMATTING ---
    def clean_cluster_labels_for_saving(label):
        if isinstance(label, str): # Handles 'EXCLUDED_FROM_CLUSTERING'
            return label
        if pd.notna(label):
            try:
                float_label = float(label)
                if float_label.is_integer():
                    return int(float_label) # Convert to int if it's a whole number like 0.0, 1.0
                return float_label # Should not occur if K-Means returns int labels
            except ValueError:
                 return str(label) # Fallback if not convertible to float
        return label # Return as is if it's already NaN or some other type

    df_all['cluster_label'] = df_all['cluster_label'].apply(clean_cluster_labels_for_saving)
    # --- END FIX ---

    df_all.drop(columns=['category_lower'], inplace=True, errors='ignore') # Remove temporary column
    
    output_file_all_data = os.path.join(BASE_DIR, 'all_news_articles_with_clusters.csv')
    try:
        df_all.to_csv(output_file_all_data, index=False)
        print(f"\nDataFrame with all articles and cluster labels saved to: {output_file_all_data}")
    except Exception as e:
        print(f"\nError saving DataFrame to CSV: {e}")

    # 8. Save the vectorizer and k-means model
    try:
        vectorizer_path = os.path.join(MODELS_DIR, 'tfidf_vectorizer_category.joblib')
        joblib.dump(vectorizer, vectorizer_path)
        print(f"TF-IDF Vectorizer saved to: {vectorizer_path}")

        kmeans_model_path = os.path.join(MODELS_DIR, 'kmeans_category_model.joblib')
        joblib.dump(kmeans, kmeans_model_path)
        print(f"K-Means Model saved to: {kmeans_model_path}")
    except Exception as e:
        print(f"\nError saving models: {e}")

    # 9. Purity check
    if n_clusters == num_unique_categories and num_unique_categories > 0 and can_compute_intrinsic_metrics:
        print("\n--- Verifying Cluster Purity (since K = num_unique_categories used for clustering) ---")
        all_clusters_pure = True
        for cluster_num in unique_assigned_clusters: # These are 0, 1, 2, ... from the `df` (filtered)
            cluster_data = df[df['cluster_label'] == cluster_num] 
            if not cluster_data.empty:
                distinct_categories_in_cluster = cluster_data['category_for_clustering'].nunique()
                if distinct_categories_in_cluster == 1:
                    actual_cat_name = cluster_data['category_for_clustering'].iloc[0]
                    print(f"Cluster {cluster_num} is pure and maps to original category: '{actual_cat_name}'")
                else:
                    all_clusters_pure = False
                    print(f"Cluster {cluster_num} is mixed. Contains {distinct_categories_in_cluster} distinct original categories used for clustering.")
                    print(f"   Categories found: {cluster_data['category_for_clustering'].value_counts().to_dict()}")
        
        if all_clusters_pure and len(unique_assigned_clusters) == n_clusters:
            print("\nConclusion for purity check: Clustering successfully mapped each unique original category (excluding 'us_news') to a distinct cluster.")
        else:
            print("\nConclusion for purity check: Clustering (excluding 'us_news') resulted in some mixed-category clusters or an imperfect mapping based on original category names.")

if __name__ == '__main__':
    main()