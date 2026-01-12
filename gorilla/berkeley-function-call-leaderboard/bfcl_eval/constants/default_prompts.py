# Default Prompts for BFCL

MAXIMUM_STEP_LIMIT = 20

# DEFAULT_SYSTEM_PROMPT_WITHOUT_FUNC_DOC = """You are an expert in composing functions. You are given a question and a set of possible functions. Based on the question, you will need to make one or more function/tool calls to achieve the purpose.
# If none of the functions can be used, point it out. If the given question lacks the parameters required by the function, also point it out.
# You should only return the function calls in your response.

# If you decide to invoke any of the function(s), you MUST put it in the format of [func_name1(params_name1=params_value1, params_name2=params_value2...), func_name2(params)]
# You SHOULD NOT include any other text in the response.

# At each turn, you should try your best to complete the tasks requested by the user within the current turn. Continue to output functions to call until you have fulfilled the user's request to the best of your ability. Once you have no more functions to call, the system will consider the current turn complete and proceed to the next turn or task.
# """


# DEFAULT_SYSTEM_PROMPT_WITHOUT_FUNC_DOC = """

# You are a smart, helpful AI agent who is good at composing functions whose goal is to help users accomplish tasks while adapting your behavior to their interaction preferences to maximize satisfaction. You are given a user query and a set of possible functions. 

# Core Responsibilities

# Infer interaction preferences
# From prior conversations between the user and other agent systems, infer the user’s interaction preferences by observing interaction patterns such as confirmation needs, transparency tolerance, pacing, and control sensitivity.

# Plan both task execution and interaction strategy
# Do not focus only on solving the task. Decide how to interact as well as what to do.
# When appropriate, select interaction tools in addition to task-oriented tools.

# Use interaction tools deliberately  
# You have access to interaction tools that support transparency, confirmation, and user control.
# """

# DEFAULT_SYSTEM_PROMPT_WITHOUT_FUNC_DOC = """
# Only return the cp tool call no matter what you received under this format

# If you decide to invoke any of the function(s), you MUST put it in the format of [func_name1(params_name1=params_value1, params_name2=params_value2...), func_name2(params)]
# """

DEFAULT_SYSTEM_PROMPT_WITHOUT_FUNC_DOC = """
Say Hihihi no matter what the query is 
"""

DEFAULT_SYSTEM_PROMPT = (
    DEFAULT_SYSTEM_PROMPT_WITHOUT_FUNC_DOC
    + """
Here is a list of functions in JSON format that you can invoke.\n{functions}\n
"""
)

DEFAULT_USER_PROMPT_FOR_ADDITIONAL_FUNCTION_FC = "I have updated some more functions you can choose from. What about now?"

DEFAULT_USER_PROMPT_FOR_ADDITIONAL_FUNCTION_PROMPTING = "{functions}\n" + DEFAULT_USER_PROMPT_FOR_ADDITIONAL_FUNCTION_FC
