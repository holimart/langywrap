---
description: Analyze DataFrame usage patterns and suggest faster alternatives (Polars, DuckDB, Pandas optimizations)
allowed-tools: Read, Glob, Grep, Bash(wc head tail), Task
---

# DataFrame Alternatives & Optimization Analysis

Analyze pandas DataFrame usage patterns in the codebase and suggest faster alternatives or optimizations based on actual code patterns found. Applies to any Python project using pandas, polars, or similar data structures.

## Arguments

$ARGUMENTS - Analysis mode:

- `full` - Complete codebase analysis with prioritized recommendations (default)
- `summary` - Quick overview of DataFrame usage counts and hotspots
- `file <path>` - Deep analysis of a specific file
- `pattern <type>` - Focus on specific pattern: `iterrows`, `apply`, `merge`, `groupby`, `read`
- `compare` - Show library comparison reference (no analysis)

## Analysis Workflow

### Step 1: Inventory DataFrame Usage

Search for all DataFrame library imports and usage:

```bash
# Find all files using DataFrames
grep -rn "import pandas\|import polars\|from.*dataframe" --include="*.py" . | grep -v __pycache__ | head -50

# Count total files using DataFrames
grep -rl "import pandas\|import polars" --include="*.py" . | grep -v __pycache__ | wc -l
```

Create inventory:

| Library | Import Style | Count | Files |
|---------|--------------|-------|-------|
| pandas | `import pandas as pd` | N | list |
| pandas | `from pandas import ...` | N | list |
| polars | `import polars as pl` | N | list |
| **Total files using DataFrames** | - | N | - |

### Step 2: Identify Performance Hotspots

Search for known slow patterns:

```bash
# CRITICAL: iterrows (100-1000x slower than vectorization)
grep -rn "\.iterrows\(\)" --include="*.py" . | grep -v __pycache__

# CRITICAL: itertuples (10x slower than vectorization, but better than iterrows)
grep -rn "\.itertuples\(\)" --include="*.py" . | grep -v __pycache__

# WARNING: apply with lambda (often slow, may be vectorizable)
grep -rn "\.apply\(lambda" --include="*.py" . | grep -v __pycache__ | head -30

# WARNING: apply with functions on rows
grep -rn "\.apply\(" --include="*.py" . | grep -v __pycache__ | head -30

# WARNING: applymap/map (row-wise operations)
grep -rn "\.applymap\(\|\.map\(" --include="*.py" . | grep -v __pycache__ | head -20

# INFO: merge/join (good candidates for DuckDB SQL)
grep -rn "\.merge\(\|\.join\(" --include="*.py" . | grep -v __pycache__ | head -20

# INFO: groupby (good candidates for Polars/DuckDB)
grep -rn "\.groupby\(" --include="*.py" . | grep -v __pycache__ | head -30

# INFO: concat (memory-intensive for many dataframes)
grep -rn "pd\.concat\|pl\.concat" --include="*.py" . | grep -v __pycache__ | head -20
```

### Step 3: Analyze Data Loading Patterns

```bash
# File reads (candidates for DuckDB direct query)
grep -rn "read_csv\|read_parquet\|read_json\|read_excel" --include="*.py" . | grep -v __pycache__ | head -30

# DataFrame conversions (integration points where optimization helps most)
grep -rn "\.to_numpy\(\)\|\.values\|\.to_pandas\(\)\|\.to_dict\(" --include="*.py" . | grep -v __pycache__ | head -20

# Large data indicators (files processing many rows)
grep -rn "len(df)\|\.shape\[0\]\|\.count\(\)" --include="*.py" . | grep -v __pycache__ | head -20
```

### Step 4: Check Modern Library Usage

```bash
# Already using Polars?
grep -rn "import polars" --include="*.py" . | grep -v __pycache__

# DuckDB for analytical queries?
grep -rn "import duckdb" --include="*.py" . | grep -v __pycache__

# Arrow integration (efficient columnar format)?
grep -rn "import pyarrow\|\.to_arrow\(\)\|\.from_arrow\(" --include="*.py" . | grep -v __pycache__
```

### Step 5: Categorize by Impact

Create hotspot table sorted by priority:

| Priority | File | Line | Pattern | Current Code | Est. Speedup | Difficulty |
|----------|------|------|---------|--------------|--------------|------------|
| P0 | path | N | iterrows | `for i, row in df.iterrows()` | 100-1000x | Low |
| P0 | path | N | apply+lambda | `.apply(lambda x: ...)` | 10-50x | Low |
| P1 | path | N | large merge | `.merge(df2, on=...)` | 5-10x | Medium |
| P1 | path | N | groupby+agg | `.groupby().agg()` | 5-20x | Medium |
| P2 | path | N | read_csv | `pd.read_csv(path)` | 5-10x | High |
| P2 | path | N | concat loop | `pd.concat([...])` | 2-5x | Low |

## Report Structure

### Executive Summary

```markdown
## DataFrame Analysis Report

**Date:** {date}
**Files Analyzed:** {count}
**Total DataFrame Usages:** {count}

### Performance Hotspot Summary

| Severity | Count | Pattern Type | Est. Total Speedup Potential |
|----------|-------|--------------|------------------------------|
| 🔴 Critical | N | iterrows, slow apply | 100-1000x improvement |
| 🟡 Warning | N | apply, applymap, merge | 5-50x improvement |
| 🟢 Optimization | N | read, concat, groupby | 2-10x improvement |

### Quick Wins (Highest ROI)

1. **{file}:{line}** - Replace iterrows with vectorization → 100x faster
2. **{file}:{line}** - Use DuckDB for large join → 10x faster
3. **{file}:{line}** - Lazy Polars for groupby chain → 5x faster
```

### Detailed Findings

For each file with hotspots:

```markdown
### {filename}

**DataFrame optimization score:** {score}/10 (higher = more optimization potential)

#### Current Patterns

| Line | Code | Issue | Priority | Alternative |
|------|------|-------|----------|-------------|
| N | `for i, row in df.iterrows()` | Extremely slow row iteration | P0 | Vectorize or use `.values` |
| N | `.apply(lambda x: func(x))` | Function per row | P1 | Use pandas `.map()` or Polars |
| N | `.merge(df2, on=...)` on 1M+ rows | Memory-intensive join | P1 | Use DuckDB SQL join |

#### Recommended Alternatives

**CRITICAL (implement immediately):**
```python
# BAD: 100-1000x slower
for i, row in df.iterrows():
    process(row['col1'], row['col2'])

# GOOD: Vectorized
df.apply(lambda row: process(row['col1'], row['col2']), axis=1)

# BEST: Pure vectorization (if possible)
result = df['col1'].combine(df['col2'], lambda x, y: process(x, y))
```

**WARNING (optimize if performance critical):**
```python
# Slower
df.apply(lambda x: x * 2)

# Faster
df * 2  # Vectorized

# For complex operations
df[['col1', 'col2']].apply(your_func, axis=1)
# Better: Use Polars expressions for complex logic
# pl_df.select([pl.col('col1').map_elements(your_func)])
```

**OPTIMIZATION (nice to have):**
```python
# Slower on large data
result = pd.concat([df1, df2, df3])

# Faster
result = pd.concat([df1, df2, df3], ignore_index=True)  # Set index once

# Best for large joins
# Use DuckDB: con.execute("SELECT * FROM df1 JOIN df2 ON ...").df()
```
```

## Library Comparison Reference

### Use Cases by Library

| Use Case | Best Library | Why | Speedup |
|----------|--------------|-----|---------|
| Small DataFrames (<100K rows) | pandas | Simple, well-known, sufficient | 1x (baseline) |
| Row iteration | Polars lazy + `.map_elements()` | 10-100x faster | 10-100x |
| Complex aggregations | Polars lazy or DuckDB SQL | Parallel execution | 5-20x |
| Large joins (1M+ rows) | DuckDB SQL | Optimized hash joins | 5-10x |
| CSV/Parquet reading | DuckDB `read_csv()` or `read_parquet()` | Direct columnar query | 5-10x |
| Group-by operations | Polars lazy | Parallel group ops | 5-20x |
| Multi-table operations | DuckDB | SQL optimizer | 5-10x |
| Real-time updates | pandas | Mutable, simpler | 1x |

### When to Use Each Library

**pandas**:
- Small datasets (<100K rows)
- Need mutable DataFrames
- ML library integration (scikit-learn, etc.)
- Already invested in pandas code

**Polars**:
- Performance critical code
- Large datasets (1M+ rows)
- Complex transformations
- Lazy evaluation benefits
- Can accept immutable DataFrames

**DuckDB**:
- SQL-heavy workloads
- Large multi-table joins
- File-based analysis (CSV/Parquet)
- No need for Python integration
- Data warehouse queries

### Migration Path Examples

```python
# pandas → Polars (simple operations)
df.groupby('category')['value'].sum()  # pandas
df.lazy().groupby('category').agg(pl.col('value').sum()).collect()  # polars

# pandas → DuckDB (for queries)
df1.merge(df2, on='key')  # pandas (slow for large data)
# DuckDB:
con.execute("SELECT * FROM df1 JOIN df2 USING (key)").df()

# Mixed approach (best of both)
# Load with DuckDB, transform with Polars, use with pandas/sklearn
df = con.execute("SELECT * FROM huge_table WHERE ...").pl()  # DuckDB→Polars
results = df.lazy().filter(...).groupby(...).agg(...).collect()  # Polars
predictions = model.predict(results.to_pandas())  # Polars→pandas for ML
```

## Implementation Guide

### Priority 1: Replace All iterrows()

This is the single biggest performance bottleneck:

```python
# BEFORE (100-1000x slower)
for idx, row in df.iterrows():
    df.loc[idx, 'new_col'] = process(row['col1'], row['col2'])

# AFTER (vectorized)
df['new_col'] = df.apply(lambda row: process(row['col1'], row['col2']), axis=1)

# BEST (if fully vectorizable)
df['new_col'] = df['col1'] * df['col2'] + 10
```

### Priority 2: Eliminate apply(lambda ...)

```python
# BEFORE (slow)
df['returns'] = df['price'].apply(lambda x: x * 0.9)

# AFTER (vectorized)
df['returns'] = df['price'] * 0.9

# Complex case
df['bucket'] = df['value'].apply(lambda x: 'high' if x > 100 else 'low')
# Better
df['bucket'] = pd.cut(df['value'], bins=[0, 100, float('inf')], labels=['low', 'high'])
```

### Priority 3: Use DuckDB for Large Joins

```python
# BEFORE (memory-intensive)
result = df1.merge(df2, on='key').merge(df3, on='id')

# AFTER (using DuckDB)
import duckdb
result = duckdb.from_df(df1).join(duckdb.from_df(df2), 'key').join(duckdb.from_df(df3), 'id').df()

# OR SQL directly
result = duckdb.query("""
    SELECT * FROM df1
    JOIN df2 USING (key)
    JOIN df3 USING (id)
""").df()
```

### Priority 4: Switch to Polars for Complex Operations

```python
# BEFORE (pandas, slower)
result = df.groupby('category').agg({
    'value': 'sum',
    'count': 'size',
    'avg': 'mean'
}).reset_index()

# AFTER (Polars, faster)
result = df.lazy().groupby('category').agg([
    pl.col('value').sum(),
    pl.col('count').count(),
    pl.col('value').mean().alias('avg')
]).collect()
```

## Validation Commands

```bash
# Find all iterrows usages
grep -rn "\.iterrows\(\)" . --include="*.py"

# Find all apply(lambda) usages
grep -rn "\.apply(lambda" . --include="*.py"

# Check for merge on large operations
grep -rn "\.merge\(" . --include="*.py" | grep -v "test"
```

## Next Steps

1. **Identify hotspots** using grep patterns above
2. **Prioritize** by P0 (critical) → P1 (important) → P2 (nice-to-have)
3. **Implement** quick wins first (iterrows removal)
4. **Measure** improvements (before/after benchmarks)
5. **Document** changes in code comments
6. **Test** thoroughly - optimizations must preserve correctness
