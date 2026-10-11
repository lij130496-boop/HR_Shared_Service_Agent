import json
from pathlib import Path
from datetime import datetime


DATA_PATH = Path(
    "data/feedback_records.jsonl"
)


def save_feedback(
        question,
        answer,
        feedback,
        reason=""
):

    DATA_PATH.parent.mkdir(
        exist_ok=True
    )


    data = {

        "time":
        datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        ),

        "question":
        question,

        "answer":
        answer,

        "feedback":
        feedback,

        "reason":
        reason,

        "status":
        "待HR处理"
    }


    with open(
        DATA_PATH,
        "a",
        encoding="utf-8"
    ) as f:

        f.write(
            json.dumps(
                data,
                ensure_ascii=False
            )
            + "\n"
        )



def load_feedback():

    if not DATA_PATH.exists():

        return []


    rows=[]


    with open(
        DATA_PATH,
        encoding="utf-8"
    ) as f:


        for line in f:

            if line.strip():

                rows.append(
                    json.loads(line)
                )


    return rows[::-1]