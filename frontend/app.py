import os
import time

import httpx
import pandas as pd
import streamlit as st

from evalbench.config import settings

API_URL = os.environ.get("EVALBENCH_API_URL", "http://localhost:8000")
SUITE_RUN_TIMEOUT = float(settings.suite_run_timeout)


st.set_page_config(page_title="EvalBench", layout="wide")
st.title("EvalBench — Local LLM Evaluation Platform")


page = st.sidebar.radio("Navigate", ["Suites", "Run Suite", "Results", "Compare Runs", "Regression"])

st.sidebar.divider()
api_key = st.sidebar.text_input(
    "API key", type="password", help="Required to start a run"
)
AUTH = {"X-API-Key": api_key} if api_key else {}


# --- Page: Suites ---
if page == "Suites":
    st.header("Test Suites")

    try:
        resp = httpx.get(f"{API_URL}/suites", timeout=10.0)
        resp.raise_for_status()
        suites = resp.json()
    except Exception as e:
        st.error(f"Cannot connect to API: {e}")
        st.stop()

    if not suites:
        st.info("No suites yet. Create one via API.")
    else:
        for suite in suites:
            with st.expander(f"{suite['name']} (Model: {suite['model']}, Evaluator: {suite['evaluator']})"):
                st.write(f"**ID:** `{suite['_id']}`")
                st.write(f"**Tests:** {len(suite.get('tests', []))}")
                df = pd.DataFrame(suite.get("tests", []))
                st.dataframe(df, width='stretch')



# --- Page: Run Suite ---
elif page == "Run Suite":
    st.header("Run a Test Suite")

    try:
        resp = httpx.get(f"{API_URL}/suites", timeout=10.0)
        resp.raise_for_status()
        suites = resp.json()
    except Exception as e:
        st.error(f"Cannot connect to API: {e}")
        st.stop()

    if not suites:
        st.warning("No suites available. Create one first.")
    else:
        suite_names = {s["name"]: s["_id"] for s in suites}
        selected_name = st.selectbox("Select Suite", list(suite_names.keys()))
        suite_id = suite_names[selected_name]

        if st.button("Run Suite", type="primary"):
            if not api_key:
                st.error("Enter your API key in the sidebar to start a run.")
                st.stop()

            try:
                resp = httpx.post(
                    f"{API_URL}/suites/{suite_id}/run",
                    headers=AUTH,
                    timeout=30.0,
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                st.error(f"Could not start run: {e.response.text[:300]}")
                st.stop()
            except Exception as e:
                st.error(f"Could not start run: {e}")
                st.stop()

            run_id = resp.json()["run_id"]
            bar = st.progress(0.0, text="Queued...")
            status_box = st.empty()
            deadline = time.monotonic() + SUITE_RUN_TIMEOUT

            while True:
                try:
                    info = httpx.get(
                        f"{API_URL}/runs/{run_id}/status",
                        headers=AUTH,
                        timeout=10.0,
                    ).json()
                except Exception as e:
                    status_box.error(f"Lost contact with the run: {e}")
                    break

                state = info.get("status", "completed")
                done = info.get("completed_tests", 0)
                total = info.get("total_tests", 0)
                frac = (done / total) if total else (
                    1.0 if state == "completed" else 0.0
                )
                bar.progress(min(frac, 1.0), text=f"{state} — {done}/{total} tests")

                if state == "completed":
                    status_box.success(f"Run completed! Run ID: `{run_id}`")
                    break
                if state == "failed":
                    status_box.error(
                        f"Run failed: {info.get('error') or 'unknown error'}"
                    )
                    break
                if time.monotonic() > deadline:
                    status_box.warning(
                        "Still running — check the Results page later."
                    )
                    break
                time.sleep(1.0)


# --- Page: Results ---
elif page == "Results":
    st.header("Run Results")

    try:
        resp = httpx.get(f"{API_URL}/suites", timeout=10.0)
        resp.raise_for_status()
        suites = resp.json()
    except Exception as e:
        st.error(f"Cannot connect to API: {e}")
        st.stop()

    if not suites:
        st.warning("No suites available.")
    else:
        suite_names = {s["name"]: s["_id"] for s in suites}
        selected_name = st.selectbox("Select Suite", list(suite_names.keys()))
        suite_id = suite_names[selected_name]

        try:
            resp = httpx.get(f"{API_URL}/suites/{suite_id}/runs", timeout=10.0)
            resp.raise_for_status()
            runs = resp.json()
        except Exception as e:
            st.error(f"Error fetching runs: {e}")
            st.stop()

        if not runs:
            st.info("No runs for this suite yet.")
        else:
            run_options = {f"Run {i+1} ({r['model']}, {r['evaluator']}) — {r['created_at'][:19]}": r["_id"]
                           for i, r in enumerate(runs)}
            selected_run = st.selectbox("Select Run", list(run_options.keys()))
            run_id = run_options[selected_run]

            try:
                resp = httpx.get(f"{API_URL}/runs/{run_id}/summary", timeout=10.0)
                resp.raise_for_status()
                summary = resp.json()
            except Exception as e:
                st.error(f"Error fetching summary: {e}")
                st.stop()

            col1, col2, col3, col4, col5 = st.columns(5)
            col1.metric("Pass Rate", f"{summary['pass_rate']*100:.1f}%")
            col2.metric("Avg Score", f"{summary['avg_score']:.3f}")
            col3.metric("Avg Latency", f"{summary['avg_latency_ms']:.0f} ms")
            col4.metric("Total Tokens", summary['total_tokens'])
            col5.metric("Errors", summary.get("errors", 0))

            by_category = summary.get("by_category") or {}
            if len(by_category) > 1:
                st.subheader("By category")
                cat_df = pd.DataFrame(
                    [
                        {
                            "Category": name,
                            "Tests": s.get("total", 0),
                            "Pass rate": f"{s.get('pass_rate', 0) * 100:.0f}%",
                            "Avg score": round(s.get("avg_score", 0), 3),
                            "Errors": s.get("errors", 0),
                        }
                        for name, s in sorted(by_category.items())
                    ]
                )
                st.dataframe(cat_df, width="stretch", hide_index=True)

            try:
                resp = httpx.get(f"{API_URL}/runs/{run_id}", timeout=30.0)
                resp.raise_for_status()
                run_doc = resp.json()
            except Exception as e:
                st.error(f"Error fetching run details: {e}")
                st.stop()

            results = run_doc.get("results", [])

            for r in results:
                icon = "✅" if r.get("passed") else "❌"
                with st.container(border=True):
                    cols = st.columns([3, 1, 1])
                    cols[0].markdown(f"**{r['test_name']}** {icon}")
                    cols[1].markdown(f"Score: `{r.get('score', 0)}`")
                    cols[2].markdown(f"Latency: `{r.get('latency_ms', 0)} ms`")

                    with st.expander("Details"):
                        st.write(f"**Prompt:** {r['prompt']}")
                        st.write(f"**Expected:** {r['expected']}")
                        st.write(f"**Actual:** {r['actual']}")
                        if r.get("error"):
                            st.error(f"Error: {r['error']}")


# --- Page: Compare Runs ---
elif page == "Compare Runs":
    st.header("Compare Two Runs")

    try:
        resp = httpx.get(f"{API_URL}/suites", timeout=10.0)
        resp.raise_for_status()
        suites = resp.json()
    except Exception as e:
        st.error(f"Cannot connect to API: {e}")
        st.stop()

    if not suites:
        st.warning("No suites available.")
    else:
        suite_names = {s["name"]: s["_id"] for s in suites}
        selected_name = st.selectbox("Select Suite", list(suite_names.keys()))
        suite_id = suite_names[selected_name]

        try:
            resp = httpx.get(f"{API_URL}/suites/{suite_id}/runs", timeout=10.0)
            resp.raise_for_status()
            runs = resp.json()
        except Exception as e:
            st.error(f"Error fetching runs: {e}")
            st.stop()

        if len(runs) < 2:
            st.info("Need at least 2 runs to compare.")
        else:
            run_options = {f"Run {i+1} ({r['model']}) — {r['created_at'][:19]}": r["_id"]
                           for i, r in enumerate(runs)}

            col1, col2 = st.columns(2)
            with col1:
                run1_name = st.selectbox("Baseline Run", list(run_options.keys()), key="r1")
            with col2:
                run2_name = st.selectbox("Current Run", list(run_options.keys()), index=min(1, len(run_options)-1), key="r2")

            run1_id = run_options[run1_name]
            run2_id = run_options[run2_name]

            if st.button("Compare", type="primary"):
                payload = {"baseline_run_id": run1_id, "current_run_id": run2_id}
                try:
                    resp = httpx.post(f"{API_URL}/regression", json=payload, timeout=15.0)
                    resp.raise_for_status()
                    comp = resp.json()
                except httpx.HTTPStatusError as e:
                    st.error(f"API error: {e.response.text[:500]}")
                    st.stop()
                except Exception as e:
                    st.error(f"Comparison failed: {e}")
                    st.stop()

                st.subheader("Comparison Result")
                c1, c2, c3 = st.columns(3)
                c1.metric("Baseline Mean", comp.get("baseline_mean", 0))
                c2.metric("Current Mean", comp.get("current_mean", 0))
                c3.metric("Mean Diff", comp.get("mean_diff", 0))

                if comp.get("regression_detected"):
                    st.error("⚠️ Regression Detected!")
                else:
                    st.success("✅ No Regression Detected")

                st.write(f"**T-Statistic:** `{comp.get('t_statistic')}`")
                st.write(f"**P-Value:** `{comp.get('p_value')}`")
                st.write(f"**Significant:** `{comp.get('significant')}`")
                if comp.get("reason"):
                    st.caption(f"Note: {comp['reason']}")


# --- Page: Regression ---
elif page == "Regression":
    st.header("Regression History")

    try:
        resp = httpx.get(f"{API_URL}/suites", timeout=10.0)
        resp.raise_for_status()
        suites = resp.json()
    except Exception as e:
        st.error(f"Cannot connect to API: {e}")
        st.stop()

    if not suites:
        st.warning("No suites available.")
    else:
        suite_names = {s["name"]: s["_id"] for s in suites}
        selected_name = st.selectbox("Select Suite", list(suite_names.keys()))
        suite_id = suite_names[selected_name]

        try:
            resp = httpx.get(f"{API_URL}/suites/{suite_id}/regression-history", timeout=15.0)
            resp.raise_for_status()
            history = resp.json()
        except httpx.HTTPStatusError as e:
            st.error(f"API error: {e.response.text[:500]}")
            st.stop()
        except Exception as e:
            st.error(f"Error fetching history: {e}")
            st.stop()

        if not history.get("comparisons"):
            st.info("Need at least 2 runs with scores for regression history.")
        else:
            st.write(f"**Total Runs:** {history.get('total_runs', 0)}")
            for comp in history["comparisons"]:
                with st.container(border=True):
                    st.write(f"**Baseline Mean:** {comp.get('baseline_mean')} | **Current Mean:** {comp.get('current_mean')}")
                    st.write(f"**P-Value:** {comp.get('p_value')} | **Significant:** {comp.get('significant')}")
                    if comp.get("regression_detected"):
                        st.error("Regression Detected")
                    else:
                        st.success("No Regression")
                    if comp.get("reason"):
                        st.caption(f"Note: {comp['reason']}")
