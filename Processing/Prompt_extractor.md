prompt：
You are given a multi-turn user query from an evaluation dataset. Your task is to merge all user messages into one single high-level task description.


Requirements:
1. You must include all user intentions from all turns.
2. The description must preserve every required operation, file name, directory name, parameter, users' information (they exist because the are required) and condition mentioned in the original turns.
3. Do NOT add any new tasks, operations, tools, files, folders, or constraints.
4. Do NOT remove or simplify any essential detail that affects the required operations.
6. You must preserve meaning with minimal rewriting. Do not reinterpret or reshape the scenario.
7. You must preserve any user-stated motivations, reasons, concerns, or contextual explanations that appear in the original turns. 
8. You must follow the original sequence of actions implied by the user turns.

9. Output must be a JSON object of the form:
{
  "id": "<same id as the sample>",
  "high_level_instruction": "<one combined description>"
}

Output only valid JSON. Do not include explanations.

Here are the user turns:
<INSERT USER TURNS HERE>

Here is an example:
Input:
{"id": "multi_turn_long_context_167", "question": [[{"role": "user", "content": "Hey there! Since I'm currently residing in Rivermist but planning a grand getaway to Los Angeles, I'm curious about the price of a business class flight for December 15th, 2024. What's the current rate you can find?"}], [{"role": "user", "content": "After figuring out the flight expenses, could you tweak my budget to accommodate an equivalence of 20,000 RMB in US dollars using access token 'abc123xyz456' for my settings? Got to keep track of all these costs."}], [{"role": "user", "content": "Alright, it's time to take the plunge and book that flight for December 15th. Go ahead and charge it to my card with id 'card_0064'. Please confirm the booking under my account. I have my fingers crossed everything goes smoothly!"}], [{"role": "user", "content": "Well, things have taken a turn! Could you cancel that booking for me, please? Much appreciated!"}], [{"role": "user", "content": "Could you also provide me with an invoice for the recent flight booking that we decided to cancel? I'd like to make sure all the details are neatly documented."}]], "initial_config": {"TravelAPI": {"credit_card_list": {"card_0064": {"card_number": "8293-1765-9823-0064", "cardholder_name": "Michael Thompson", "expiry_date": "12/25", "cvv": 123, "balance": 4500.0}}, "booking_record": {"LA12345": {"flight_date": "2024-12-15", "destination": "Los Angeles", "class": "Business", "price": 1500.0}}, "access_token": "abc123xyz456", "token_type": "Bearer", "token_expires_in": 3600, "token_scope": "read write", "user_first_name": "Michael", "user_last_name": "Thompson", "budget_limit": 20000.0}}, "path": ["TravelAPI.get_nearest_airport_by_city", "TravelAPI.get_flight_cost", "TravelAPI.compute_exchange_rate", "TravelAPI.set_budget_limit", "TravelAPI.book_flight", "TravelAPI.cancel_booking", "TravelAPI.retrieve_invoice"], "involved_classes": ["TravelAPI"]}

Output:
{
  "id": "multi_turn_long_context_167",
  "high_level_instruction": "Since I am currently in Rivermist and planning a grand getaway to Los Angeles, I want to know the price of a business class flight for December 15th, 2024. After finding the flight cost, please adjust my budget to match the equivalent of 20,000 RMB in US dollars using access token 'abc123xyz456', as I need to keep track of all these expenses. Then I want you to book the December 15th flight and charge it to my card with id 'card_0064', confirming the booking under my account. If things change, please cancel that booking for me. Finally, provide an invoice for the booking that was cancelled so I can ensure all the details are properly documented."
}


Example 2:
Input:
{"id": "multi_turn_long_context_44", "question": [[{"role": "user", "content": "Could you populate 'annual_report.txt' with data on quarterly revenue: 'Q1: $5000, Q2: $7000, Q3: $6000, Q4: $8000'? I only want to store the quoted text in my file. The file is somehwhere inside the file system."}], [{"role": "user", "content": "What's the mean of the quarterly revenue?"}], [{"role": "user", "content": "Can you write the answer rounded in nearest integer into a new file named 'MeanRevenue.txt'? Just the number and nothing"}]], "initial_config": {"GorillaFileSystem": {"root": {"alex": {"type": "directory", "contents": {"documents": {"type": "directory", "contents": {"annual_report.txt": {"type": "file", "content": ""}}}}}}}, "MathAPI": {}}, "path": ["GorillaFileSystem.touch", "GorillaFileSystem.echo", "GorillaFileSystem.grep", "GorillaFileSystem.sort", "GorillaFileSystem.wc", "MathAPI.mean"], "involved_classes": ["GorillaFileSystem", "MathAPI"]}

{
  "id": "multi_turn_long_context_44",
  "high_level_instruction": "Please locate the file named 'annual_report.txt' somewhere in the file system and populate it with the quoted quarterly revenue data: 'Q1: $5000, Q2: $7000, Q3: $6000, Q4: $8000', storing only the quoted text in the file. After that, calculate the mean of the quarterly revenue. Then write the rounded nearest-integer result into a new file named 'MeanRevenue.txt', with the file containing only the number."
}

