import { Select, type ComboboxItem, type OptionsFilter, type SelectProps } from "@mantine/core";

import type { MemberSummary } from "../api/client";

/** What a member is found by: their name, their member ID and the GitHub account they sign in with. */
function words(member: MemberSummary): string {
  return [member.name, member.member_id, member.github_login ?? ""].join(" ").toLowerCase();
}

/**
 * Choose a member of the team by name, member ID or GitHub account, so nobody has to look an ID up on Team first.
 * Its value is still the member ID, so what is sent is unchanged.
 */
export function MemberPicker({
  members,
  ...props
}: { members: MemberSummary[] } & Omit<SelectProps, "data" | "filter" | "renderOption" | "searchable">) {
  const byId = new Map(members.map((one) => [one.member_id, one]));
  const filter: OptionsFilter = ({ options, search }) => {
    const asked = search.trim().toLowerCase().replace(/^@/, "");
    if (!asked) return options;
    return options.filter((option) => {
      const member = byId.get((option as ComboboxItem).value);
      return member !== undefined && words(member).includes(asked);
    });
  };
  return (
    <Select
      searchable
      nothingFoundMessage="No member of the team matches."
      // As wide as the longest member, so a name, ID and GitHub account stay on one line beside a narrow filter.
      comboboxProps={{ width: "max-content", position: "bottom-start" }}
      classNames={{ dropdown: "member-picker-dropdown" }}
      {...props}
      data={members.map((one) => ({ value: one.member_id, label: one.name }))}
      filter={filter}
      renderOption={({ option }) => {
        const member = byId.get(option.value);
        if (!member) return option.label;
        return (
          <span className="member-option">
            <span className="member-option-name">{member.name}</span>
            <span className="member-option-meta">
              {" · "}
              <span className="member-id">{member.member_id}</span>
              {member.github_login && ` · @${member.github_login}`}
              {member.removed && " · has left the team"}
            </span>
          </span>
        );
      }}
    />
  );
}
