# Usage

## Initialize

Now that you've configured a provider, navigate to a project you want to work on:

```bash
cd /path/to/project
```

And run iTE:

```bash
ite
```

Next, initialize iTE for the project by running:

```
/init
```

This will analyze your project and create an `AGENTS.md` file in the project root.

> **Tip:** Commit your project's AGENTS.md file to Git. This helps iTE understand the project structure and coding patterns used across your team.

## Usage

You are now ready to use iTE to work on your project. Feel free to ask it anything!

If you are new to using an AI coding agent, here are some examples that might help.

### Ask Questions

You can ask iTE to explain the codebase to you:

```
How is authentication handled in src/auth/index.ts
```

> **Tip:** Use the `@` key to fuzzy search for files in the project.

This is helpful if there's a part of the codebase that you didn't work on.

### Add Features

You can ask iTE to add new features to your project. We first recommend asking it to create a plan.

**1. Create a plan**

iTE has a Plan mode that disables its ability to make changes and instead suggests how it'll implement the feature.

Enable it by running:

```
/plan on
```

Now describe what you want it to do:

```
When a user deletes a note, we'd like to flag it as deleted in the database.
Then create a screen that shows all the recently deleted notes.
From this screen, the user can undelete a note or permanently delete it.
```

**2. Iterate on the plan**

Once it gives you a plan, you can give it feedback or add more details:

```
We'd like to design this new screen using a design I've used before.
```

**3. Build the feature**

Once you feel comfortable with the plan, disable plan mode:

```
/plan off
```

And ask it to make the changes:

```
Sounds good! Go ahead and make the changes.
```

### Make Changes

For more straightforward changes, you can ask iTE to directly build without reviewing the plan first:

```
We need to add authentication to the /settings route. Take a look at how this is
handled in the /notes route in src/notes.ts and implement
the same logic in src/settings.ts
```

### Undo Changes

If something goes wrong, you can undo:

```
/undo
```

Reverts file changes from the last turn. Or redo if you change your mind:

```
/redo
```

## Sessions

Conversations auto-save. List or resume previous sessions:

```
/sessions
```

## Commands

Type `/help` for a full list of commands.

---

[Full command reference →](commands.md)
