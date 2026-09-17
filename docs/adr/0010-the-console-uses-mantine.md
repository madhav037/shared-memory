# The console's screens are built with Mantine

The console uses [Mantine](https://mantine.dev) for its components — tables, forms, dialogs, layout — rather than hand-written styling. The console is mostly tables, filters and forms over the server's data, and those are exactly the parts that are slow to hand-roll and easy to get wrong for keyboard and screen-reader users.

## Considered Options

- **Hand-written CSS**: fine for the first screen, but the spec's later tickets add memory trees, diffs, member tables and access lists, and each would mean rebuilding the same controls.
- **shadcn/ui**: components copied into the repository rather than installed, which gives more control, but brings Tailwind and its configuration along with it.

## Consequences

- Mantine's provider, theme and CSS layer sit at the console's root, and its PostCSS preset is part of the build.
- Screens use Mantine's components by default; anything custom is the exception and should look like it belongs beside them.
- Mantine carries its own look. The theme keeps it quiet, because the memory is what should stand out, not the console.
