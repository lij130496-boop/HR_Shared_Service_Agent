from collections import Counter



def hot_questions(records):


    questions=[

        x["question"]

        for x in records

    ]


    return Counter(
        questions
    ).most_common(10)