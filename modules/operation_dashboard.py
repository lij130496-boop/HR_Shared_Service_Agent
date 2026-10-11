import streamlit as st

from modules.feedback_manager import load_feedback



def render_operation_dashboard():


    st.subheader(
        "📊 AI智能运营优化中心"
    )


    records = load_feedback()


    if not records:

        st.info(
            "暂无员工反馈数据"
        )

        return



    total=len(records)


    bad=[
        x for x in records
        if x["feedback"]=="未解决"
    ]



    col1,col2,col3=st.columns(3)



    with col1:

        st.metric(
            "累计咨询反馈",
            total
        )


    with col2:

        st.metric(
            "待优化问题",
            len(bad)
        )


    with col3:

        rate=(
            (total-len(bad))
            /
            total
            *
            100
        )


        st.metric(
            "解决率",
            f"{rate:.1f}%"
        )



    st.divider()


    st.subheader(
        "❌ 未解决问题池"
    )


    for item in bad:


        with st.container(
            border=True
        ):


            st.write(
                "时间:",
                item["time"]
            )


            st.write(
                "员工问题:",
                item["question"]
            )


            st.write(
                "AI回答:",
                item["answer"]
            )


            st.write(
                "原因:",
                item["reason"]
            )
