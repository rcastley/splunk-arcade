import json
import os
from random import choice, randint, random

from redis import StrictRedis

SPLUNK_OBSERVABILITY_REALM = os.getenv("SPLUNK_OBSERVABILITY_REALM", "us1")

# for now, 30% of the time we'll try to use a ai gen question
OPENAI_QUESTION_CHANCE_THRESHOLD = 0.3
MAX_QUESTION_SELECTION_ATTEMPTS = 15

# mapping is obviously game, then count of seen questions: index of question to show (as in the
# position in the array of the questions.json for the given game)
# a: b
# a = position in json (under game, with is_fixed_position=true
# b = question order
FIXED_POSITION_QUESTIONS = {
    "imvaders": {
        0: 0,
        1: 1,
        2: 2,
        3: 3,
        4: 4,
    },
    "logger": {
        0: 0,
        1: 1,
        2: 2,
        3: 3,
        4: 4,
    },
    "bughunt": {},
    "floppybird": {},
}


class _Questions:
    _instance = None

    def __new__(cls):
        if not cls._instance:
            cls._instance = super().__new__(cls)

        return cls._instance

    def __init__(self):
        self.f = open("questions.json", mode="r")
        self.content = json.load(self.f)
        self.redis = StrictRedis(
            host=os.getenv("REDIS_HOST", "cache"),
            port=6379,
            db=0,
            decode_responses=True,
        )

    def _get_random_generated_question_for_module(
        self,
        module: str,
        player_name: str,
    ) -> dict | None:
        key_namespace = f"content:quiz:{module}:{player_name}:*"

        found_keys = self.redis.keys(pattern=key_namespace)
        if not found_keys:
            return None

        random_key = choice(found_keys)

        loaded_content = self.redis.hgetall(random_key)
        loaded_content["choices"] = json.loads(loaded_content["choices"])

        return loaded_content

    def _get_random_static_question_for_module(
        self,
        module: str,
    ) -> dict | None:
        while True:
            maybe_question = self.content[module][randint(0, len(self.content[module]) - 1)]
            if maybe_question.get("is_fixed_position"):
                continue

            return maybe_question

    def random_question_for_module(
        self, module: str, seen_questions: [str], player_name: str
    ) -> dict:
        _module = module.lower()

        if _module not in self.content:
            # in the future we may need/want to check dynamic questions as we may not even have
            # "static" questions, but for now this is a safe check to ensure we dont try to load
            # a question for some module (game) that doesnt exist
            raise Exception(f"module '{module}' is not in questions bank")

        fixed_question_data = FIXED_POSITION_QUESTIONS.get(_module, None)
        if fixed_question_data:
            maybe_fixed_question_index = fixed_question_data.get(len(seen_questions), None)
            if maybe_fixed_question_index is not None:
                the_question = self.content[module][maybe_fixed_question_index]
                the_question["question"] = the_question["question"].replace(
                    "__PLAYER_NAME__", player_name
                )
                if "link" in the_question:
                    the_question["link"] = the_question["link"].replace(
                        "__PLAYER_NAME__", player_name
                    )
                    the_question["link"] = the_question["link"].replace(
                        "__REALM__",
                        SPLUNK_OBSERVABILITY_REALM,
                    )

                return the_question

        attempts = 0

        while True:
            if random() < OPENAI_QUESTION_CHANCE_THRESHOLD:
                maybe_question = self._get_random_generated_question_for_module(
                    module=_module,
                    player_name=player_name,
                )
            else:
                maybe_question = self._get_random_static_question_for_module(
                    module=_module,
                )

            if maybe_question and maybe_question["question"] not in seen_questions:
                maybe_question["question"] = maybe_question["question"].replace(
                    "__PLAYER_NAME__", player_name
                )
                if "link" in maybe_question:
                    maybe_question["link"] = maybe_question["link"].replace(
                        "__PLAYER_NAME__", player_name
                    )
                    maybe_question["link"] = maybe_question["link"].replace(
                        "__REALM__",
                        SPLUNK_OBSERVABILITY_REALM,
                    )

                return maybe_question

            attempts += 1

            if attempts > MAX_QUESTION_SELECTION_ATTEMPTS:
                # lets not try forever... if we didnt get a not seen question in this amount of
                # attempts we can be done for now...
                return {}
