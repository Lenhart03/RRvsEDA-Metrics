#!/usr/bin/env python3
"""
Visualization script for comparing Request-Response vs Event-Driven architectures.
Creates comprehensive comparison plots from Locust CSV results.
"""

import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns
from pathlib import Path

# Set style
sns.set_style("whitegrid")
plt.rcParams['figure.figsize'] = (14, 8)
plt.rcParams['font.size'] = 10

def load_data(rr_files, eda_files):
    """Load and combine RR and EDA CSV files."""
    rr_dfs = [pd.read_csv(f) for f in rr_files]
    eda_dfs = [pd.read_csv(f) for f in eda_files]
    
    rr_df = pd.concat(rr_dfs, ignore_index=True)
    eda_df = pd.concat(eda_dfs, ignore_index=True)
    
    return rr_df, eda_df


def plot_latency_comparison(rr_df, eda_df, output_file="01_latency_comparison.png"):
    """
    Side-by-side comparison of latency metrics across different user loads.
    Shows median, P95, P99 for both architectures.
    """
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    
    metrics = [
        ('Median (ms)', 'Median Latency'),
        ('P95 (ms)', 'P95 Latency'),
        ('P99 (ms)', 'P99 Latency')
    ]
    
    x = np.arange(len(rr_df))
    width = 0.35
    
    for idx, (metric, title) in enumerate(metrics):
        ax = axes[idx]
        
        bars1 = ax.bar(x - width/2, rr_df[metric], width, 
                       label='Request-Response', color='#e74c3c', alpha=0.8)
        bars2 = ax.bar(x + width/2, eda_df[metric], width,
                       label='Event-Driven', color='#3498db', alpha=0.8)
        
        ax.set_xlabel('User Load')
        ax.set_ylabel('Latency (ms)')
        ax.set_title(title, fontweight='bold', fontsize=12)
        ax.set_xticks(x)
        ax.set_xticklabels([f"{int(u)} users" for u in rr_df['Users']])
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        # Add value labels on bars
        for bars in [bars1, bars2]:
            for bar in bars:
                height = bar.get_height()
                ax.annotate(f'{height:.0f}',
                           xy=(bar.get_x() + bar.get_width() / 2, height),
                           xytext=(0, 3),
                           textcoords="offset points",
                           ha='center', va='bottom',
                           fontsize=8)
    
    plt.tight_layout()
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"✅ Saved: {output_file}")
    plt.close()


def plot_throughput_comparison(rr_df, eda_df, output_file="02_throughput_comparison.png"):
    """
    Compare requests/second between architectures.
    """
    fig, ax = plt.subplots(figsize=(12, 6))
    
    x = np.arange(len(rr_df))
    width = 0.35
    
    bars1 = ax.bar(x - width/2, rr_df['Requests/sec'], width,
                   label='Request-Response', color='#e74c3c', alpha=0.8)
    bars2 = ax.bar(x + width/2, eda_df['Requests/sec'], width,
                   label='Event-Driven', color='#3498db', alpha=0.8)
    
    ax.set_xlabel('User Load', fontweight='bold')
    ax.set_ylabel('Throughput (requests/second)', fontweight='bold')
    ax.set_title('Throughput Comparison: RR vs EDA', fontweight='bold', fontsize=14)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{int(u)} users" for u in rr_df['Users']])
    ax.legend(fontsize=11)
    ax.grid(True, alpha=0.3, axis='y')
    
    # Add value labels
    for bars in [bars1, bars2]:
        for bar in bars:
            height = bar.get_height()
            ax.annotate(f'{height:.1f}',
                       xy=(bar.get_x() + bar.get_width() / 2, height),
                       xytext=(0, 3),
                       textcoords="offset points",
                       ha='center', va='bottom',
                       fontsize=9)
    
    plt.tight_layout()
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"✅ Saved: {output_file}")
    plt.close()


def plot_latency_breakdown(rr_df, eda_df, output_file="03_latency_breakdown.png"):
    """
    Show min/avg/median/p95/p99/max as a line plot for each architecture.
    """
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))
    
    users = rr_df['Users'].values
    
    # Request-Response
    ax1.plot(users, rr_df['Min (ms)'], marker='o', label='Min', linewidth=2)
    ax1.plot(users, rr_df['Average (ms)'], marker='s', label='Average', linewidth=2)
    ax1.plot(users, rr_df['Median (ms)'], marker='^', label='Median', linewidth=2)
    ax1.plot(users, rr_df['P95 (ms)'], marker='d', label='P95', linewidth=2)
    ax1.plot(users, rr_df['P99 (ms)'], marker='*', label='P99', linewidth=2, markersize=10)
    ax1.plot(users, rr_df['Max (ms)'], marker='x', label='Max', linewidth=2, markersize=8)
    
    ax1.set_xlabel('Concurrent Users', fontweight='bold')
    ax1.set_ylabel('Latency (ms)', fontweight='bold')
    ax1.set_title('Request-Response Latency Distribution', fontweight='bold', fontsize=12)
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # Event-Driven
    ax2.plot(users, eda_df['Min (ms)'], marker='o', label='Min', linewidth=2)
    ax2.plot(users, eda_df['Average (ms)'], marker='s', label='Average', linewidth=2)
    ax2.plot(users, eda_df['Median (ms)'], marker='^', label='Median', linewidth=2)
    ax2.plot(users, eda_df['P95 (ms)'], marker='d', label='P95', linewidth=2)
    ax2.plot(users, eda_df['P99 (ms)'], marker='*', label='P99', linewidth=2, markersize=10)
    ax2.plot(users, eda_df['Max (ms)'], marker='x', label='Max', linewidth=2, markersize=8)
    
    ax2.set_xlabel('Concurrent Users', fontweight='bold')
    ax2.set_ylabel('Latency (ms)', fontweight='bold')
    ax2.set_title('Event-Driven Latency Distribution', fontweight='bold', fontsize=12)
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"✅ Saved: {output_file}")
    plt.close()


def plot_speedup_factor(rr_df, eda_df, output_file="04_speedup_factor.png"):
    """
    Show how many times faster EDA is compared to RR.
    """
    fig, ax = plt.subplots(figsize=(12, 6))
    
    metrics = ['Median (ms)', 'Average (ms)', 'P95 (ms)', 'P99 (ms)']
    colors = ['#2ecc71', '#f39c12', '#e74c3c', '#9b59b6']
    
    x = np.arange(len(rr_df))
    width = 0.2
    
    for idx, metric in enumerate(metrics):
        speedup = rr_df[metric] / eda_df[metric]
        offset = (idx - len(metrics)/2 + 0.5) * width
        
        bars = ax.bar(x + offset, speedup, width, 
                     label=metric.replace(' (ms)', ''),
                     color=colors[idx], alpha=0.8)
        
        # Add value labels
        for bar in bars:
            height = bar.get_height()
            ax.annotate(f'{height:.1f}x',
                       xy=(bar.get_x() + bar.get_width() / 2, height),
                       xytext=(0, 3),
                       textcoords="offset points",
                       ha='center', va='bottom',
                       fontsize=8, fontweight='bold')
    
    ax.axhline(y=1, color='black', linestyle='--', linewidth=1, alpha=0.5, label='Equal Performance')
    ax.set_xlabel('User Load', fontweight='bold')
    ax.set_ylabel('Speedup Factor (RR / EDA)', fontweight='bold')
    ax.set_title('EDA Performance Advantage (Higher is Better)', fontweight='bold', fontsize=14)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{int(u)} users" for u in rr_df['Users']])
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3, axis='y')
    
    plt.tight_layout()
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"✅ Saved: {output_file}")
    plt.close()


def plot_scalability_analysis(rr_df, eda_df, output_file="05_scalability_analysis.png"):
    """
    Analyze how latency grows with user load (logarithmic scale).
    """
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))
    
    users = rr_df['Users'].values
    
    # Latency Growth
    ax1.plot(users, rr_df['Median (ms)'], marker='o', label='RR Median',
            linewidth=2.5, markersize=8, color='#e74c3c')
    ax1.plot(users, eda_df['Median (ms)'], marker='s', label='EDA Median',
            linewidth=2.5, markersize=8, color='#3498db')
    ax1.plot(users, rr_df['P99 (ms)'], marker='o', label='RR P99',
            linewidth=2, markersize=7, linestyle='--', color='#c0392b')
    ax1.plot(users, eda_df['P99 (ms)'], marker='s', label='EDA P99',
            linewidth=2, markersize=7, linestyle='--', color='#2980b9')
    
    ax1.set_xlabel('Concurrent Users', fontweight='bold')
    ax1.set_ylabel('Latency (ms)', fontweight='bold')
    ax1.set_title('Latency Scaling Under Load', fontweight='bold', fontsize=12)
    ax1.set_yscale('log')
    ax1.legend()
    ax1.grid(True, alpha=0.3, which='both')
    
    # Throughput Growth
    ax2.plot(users, rr_df['Requests/sec'], marker='o', label='Request-Response',
            linewidth=2.5, markersize=8, color='#e74c3c')
    ax2.plot(users, eda_df['Requests/sec'], marker='s', label='Event-Driven',
            linewidth=2.5, markersize=8, color='#3498db')
    
    ax2.set_xlabel('Concurrent Users', fontweight='bold')
    ax2.set_ylabel('Throughput (req/s)', fontweight='bold')
    ax2.set_title('Throughput Scaling Under Load', fontweight='bold', fontsize=12)
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"✅ Saved: {output_file}")
    plt.close()


def plot_summary_dashboard(rr_df, eda_df, output_file="06_summary_dashboard.png"):
    """
    Create a comprehensive dashboard with key metrics.
    """
    fig = plt.figure(figsize=(18, 10))
    gs = fig.add_gridspec(3, 3, hspace=0.3, wspace=0.3)
    
    # 1. Median Latency Comparison
    ax1 = fig.add_subplot(gs[0, :2])
    x = np.arange(len(rr_df))
    width = 0.35
    ax1.bar(x - width/2, rr_df['Median (ms)'], width, label='RR', color='#e74c3c', alpha=0.8)
    ax1.bar(x + width/2, eda_df['Median (ms)'], width, label='EDA', color='#3498db', alpha=0.8)
    ax1.set_title('Median Latency', fontweight='bold')
    ax1.set_xticks(x)
    ax1.set_xticklabels([f"{int(u)}" for u in rr_df['Users']])
    ax1.set_ylabel('ms')
    ax1.legend()
    ax1.grid(True, alpha=0.3, axis='y')
    
    # 2. Success Rate
    ax2 = fig.add_subplot(gs[0, 2])
    avg_success_rr = rr_df['Success Rate (%)'].mean()
    avg_success_eda = eda_df['Success Rate (%)'].mean()
    ax2.bar(['RR', 'EDA'], [avg_success_rr, avg_success_eda], 
           color=['#e74c3c', '#3498db'], alpha=0.8)
    ax2.set_title('Average Success Rate', fontweight='bold')
    ax2.set_ylabel('%')
    ax2.set_ylim([0, 105])
    ax2.grid(True, alpha=0.3, axis='y')
    for i, v in enumerate([avg_success_rr, avg_success_eda]):
        ax2.text(i, v + 1, f'{v:.1f}%', ha='center', fontweight='bold')
    
    # 3. P95 Latency
    ax3 = fig.add_subplot(gs[1, :2])
    ax3.bar(x - width/2, rr_df['P95 (ms)'], width, label='RR', color='#e74c3c', alpha=0.8)
    ax3.bar(x + width/2, eda_df['P95 (ms)'], width, label='EDA', color='#3498db', alpha=0.8)
    ax3.set_title('P95 Latency', fontweight='bold')
    ax3.set_xticks(x)
    ax3.set_xticklabels([f"{int(u)}" for u in rr_df['Users']])
    ax3.set_ylabel('ms')
    ax3.legend()
    ax3.grid(True, alpha=0.3, axis='y')
    
    # 4. Total Requests
    ax4 = fig.add_subplot(gs[1, 2])
    total_rr = rr_df['Total Requests'].sum()
    total_eda = eda_df['Total Requests'].sum()
    ax4.bar(['RR', 'EDA'], [total_rr, total_eda], 
           color=['#e74c3c', '#3498db'], alpha=0.8)
    ax4.set_title('Total Requests Processed', fontweight='bold')
    ax4.grid(True, alpha=0.3, axis='y')
    for i, v in enumerate([total_rr, total_eda]):
        ax4.text(i, v + max(total_rr, total_eda)*0.02, f'{v:,}', ha='center', fontweight='bold')
    
    # 5. Throughput
    ax5 = fig.add_subplot(gs[2, :2])
    ax5.bar(x - width/2, rr_df['Requests/sec'], width, label='RR', color='#e74c3c', alpha=0.8)
    ax5.bar(x + width/2, eda_df['Requests/sec'], width, label='EDA', color='#3498db', alpha=0.8)
    ax5.set_title('Throughput', fontweight='bold')
    ax5.set_xlabel('Concurrent Users')
    ax5.set_xticks(x)
    ax5.set_xticklabels([f"{int(u)}" for u in rr_df['Users']])
    ax5.set_ylabel('req/s')
    ax5.legend()
    ax5.grid(True, alpha=0.3, axis='y')
    
    # 6. Key Stats Table
    ax6 = fig.add_subplot(gs[2, 2])
    ax6.axis('off')
    
    stats_text = f"""
    KEY FINDINGS
    {'='*30}
    
    Avg Speedup (Median):
      {(rr_df['Median (ms)'] / eda_df['Median (ms)']).mean():.1f}x faster
    
    Throughput (200 users):
      RR:  {rr_df.iloc[-1]['Requests/sec']:.1f} req/s
      EDA: {eda_df.iloc[-1]['Requests/sec']:.1f} req/s
    
    Latency at Scale (200u):
      RR:  {rr_df.iloc[-1]['Median (ms)']:.0f} ms
      EDA: {eda_df.iloc[-1]['Median (ms)']:.0f} ms
    """
    
    ax6.text(0.1, 0.5, stats_text, fontsize=10, family='monospace',
            verticalalignment='center')
    
    fig.suptitle('RR vs EDA Performance Dashboard', 
                fontsize=16, fontweight='bold', y=0.98)
    
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"✅ Saved: {output_file}")
    plt.close()


def main():
    """Main execution function."""
    print("🎨 Generating RR vs EDA comparison plots...\n")
    
    # Load data - adjust these paths to match your files
    rr_files = ['rr_50users.csv', 'rr_100users.csv', 'rr_200users.csv']
    eda_files = ['eda_50users.csv', 'eda_100users.csv', 'eda_200users.csv']
    
    # Check if files exist
    for f in rr_files + eda_files:
        if not Path(f).exists():
            print(f"❌ Error: {f} not found!")
            print(f"💡 Make sure you have run the load tests first.")
            return
    
    rr_df, eda_df = load_data(rr_files, eda_files)
    
    # Create output directory
    output_dir = Path("comparison_plots")
    output_dir.mkdir(exist_ok=True)
    
    # Generate all plots
    plot_latency_comparison(rr_df, eda_df, output_dir / "01_latency_comparison.png")
    plot_throughput_comparison(rr_df, eda_df, output_dir / "02_throughput_comparison.png")
    plot_latency_breakdown(rr_df, eda_df, output_dir / "03_latency_breakdown.png")
    plot_speedup_factor(rr_df, eda_df, output_dir / "04_speedup_factor.png")
    plot_scalability_analysis(rr_df, eda_df, output_dir / "05_scalability_analysis.png")
    plot_summary_dashboard(rr_df, eda_df, output_dir / "06_summary_dashboard.png")
    
    print(f"\n🎉 All plots saved to '{output_dir}/' directory!")
    print("\n📊 Recommended viewing order:")
    print("   1. 06_summary_dashboard.png - Overall comparison")
    print("   2. 01_latency_comparison.png - Latency metrics")
    print("   3. 04_speedup_factor.png - Performance advantage")
    print("   4. 05_scalability_analysis.png - Scaling behavior")


if __name__ == "__main__":
    main()