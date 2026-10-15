import subprocess


def menu():
    print("\n\n1. Add task")
    print("2. Add observation")
    print("3. Add follow-up action")
    print("4. Entry is complete. Save entry\n")


def menu_selection():
    while True:
        try:
            selection = int(input("Select an option number 1-4: "))

            if 1 <= selection <= 4:
                return selection
            else:
                print("Error! Enter a number between 1-4")

        except ValueError:
            print("Error! Enter numbers only!")


def add_task():
    task = input(
        "Add a task and press ENTER. "
        "If there is nothing to add, just press ENTER\n: "
    ).strip()

    if task == "":
        return None

    return task


def add_observation():
    observation = input(
        "Add an observation and press ENTER. "
        "If there is nothing to add, just press ENTER: "
    ).strip()

    if observation == "":
        return None

    return observation


def add_follow_up_action():
    follow_up_action = input(
        "Add a follow-up action and press ENTER. "
        "If there is nothing to add, just press ENTER: "
    ).strip()

    if follow_up_action == "":
        return None

    return follow_up_action


def create_entry(tasks, observations, follow_up_actions):
    if not tasks and not observations and not follow_up_actions:
        return None

    return {
        "tasks": tasks,
        "observations": observations,
        "follow_up_actions": follow_up_actions
    }


def clear_screen():
    subprocess.run(
        ["clear"],
        check=False
    )


def main():
    tasks_list = []
    observations_list = []
    follow_up_actions_list = []

    while True:
        menu()
        selection = menu_selection()

        if selection == 1:
            clear_screen()
            task = add_task()

            if task is not None:
                tasks_list.append(task)

            print("\nAdded tasks:", tasks_list)

        elif selection == 2:
            clear_screen()
            observation = add_observation()

            if observation is not None:
                observations_list.append(observation)

            print("\nAdded observations:", observations_list)

        elif selection == 3:
            clear_screen()
            follow_up_action = add_follow_up_action()

            if follow_up_action is not None:
                follow_up_actions_list.append(follow_up_action)

            print("\nAdded follow-up actions:", follow_up_actions_list)

        elif selection == 4:
            clear_screen()

            entry = create_entry(
                tasks_list,
                observations_list,
                follow_up_actions_list
            )

            if entry is None:
                print("Entry was not created because there are no items.")
            else:
                print("\nEntry:")
                print(entry)

            break


if __name__ == "__main__":
    main()