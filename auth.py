import json
import os
import hashlib


USER_FILE = "data/users.json"


def init_user_file():

    os.makedirs("data", exist_ok=True)

    if not os.path.exists(USER_FILE):

        with open(
            USER_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                {},
                f
            )



def hash_password(password):

    return hashlib.sha256(
        password.encode("utf-8")
    ).hexdigest()



def load_users():

    init_user_file()

    with open(
        USER_FILE,
        "r",
        encoding="utf-8"
    ) as f:

        return json.load(f)



def save_users(users):

    with open(
        USER_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            users,
            f,
            ensure_ascii=False,
            indent=4
        )



def register(username,password):

    users = load_users()


    if username in users:

        return False,"用户已经存在"



    users[username]={

        "password":
            hash_password(password),

        "role":
            "普通员工"

    }


    save_users(users)


    return True,"注册成功"



def login(username,password):

    users = load_users()


    if username not in users:

        return False,None


    if users[username]["password"] != hash_password(password):

        return False,None


    return True,users[username]