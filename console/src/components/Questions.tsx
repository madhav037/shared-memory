import { Button, Textarea } from "@mantine/core";
import { IconHelpCircle } from "@tabler/icons-react";
import { useState } from "react";

import {
  answerQuestion,
  askQuestion,
  fetchQuestionsOn,
  type MemoryDetail,
  type MemoryQuestions,
  type QuestionThread,
} from "../api/client";
import { moment } from "../lib/format";
import { useAsked } from "../lib/useAsked";
import { Refusal } from "./Bits";

/**
 * The questions members asked about a memory, each with its answers (ADR-0028), and a form to ask its author one.
 * Asking and answering never change the memory: a change an answer calls for is made in a session (ADR-0009).
 */
export function Questions({ memory }: { memory: MemoryDetail }) {
  const { answer: asked } = useAsked((signal) => fetchQuestionsOn(memory.path, signal), [memory.path]);
  const [shown, setShown] = useState<MemoryQuestions | null>(null);
  const questions = shown?.path === memory.path ? shown : asked;
  if (!questions) return null;
  const changed = (anew: MemoryQuestions) => setShown(anew);

  return (
    <section className="talk questions" aria-labelledby="questions-heading" data-testid="questions">
      <h2 className="talk-head" id="questions-heading">
        <IconHelpCircle size={18} stroke={1.6} aria-hidden />
        Questions
        {questions.open > 0 && <span className="mark">{questions.open} open</span>}
      </h2>
      <p className="talk-lede">
        {questions.threads.length === 0
          ? "No one has asked about this memory yet."
          : "Anyone who can read this memory reads these, and may answer."}{" "}
        An answer never changes the memory: if it should change, its author does that in a session.
      </p>
      {questions.threads.length > 0 && (
        <ol className="talk-list">
          {questions.threads.map((thread) => (
            <Thread
              key={thread.question_id}
              path={memory.path}
              thread={thread}
              textLimit={questions.text_limit}
              onChanged={changed}
            />
          ))}
        </ol>
      )}
      {questions.may_ask && memory.status === "active" && (
        <Ask
          path={memory.path}
          authorName={memory.author_name}
          textLimit={questions.text_limit}
          onChanged={changed}
        />
      )}
    </section>
  );
}

function Thread({
  path,
  thread,
  textLimit,
  onChanged,
}: {
  path: string;
  thread: QuestionThread;
  textLimit: number;
  onChanged: (anew: MemoryQuestions) => void;
}) {
  return (
    <li data-testid="question">
      <p className="talk-meta">
        <b title={thread.asked_by}>{thread.asked_by_name}</b> asked,{" "}
        <time dateTime={thread.asked_at}>{moment(thread.asked_at)}</time> ·{" "}
        <span data-testid="question-state">{thread.state === "open" ? "Open" : "Answered"}</span>
      </p>
      <p className="talk-text" data-testid="question-text">
        {thread.text}
      </p>
      {thread.answers.length > 0 && (
        <ol className="question-answers">
          {thread.answers.map((one, place) => (
            <li key={place} data-testid="question-answer">
              <p className="talk-meta">
                <b title={one.by}>{one.by_name}</b> answered, <time dateTime={one.at}>{moment(one.at)}</time>
              </p>
              <p className="talk-text">{one.text}</p>
            </li>
          ))}
        </ol>
      )}
      <Said
        label="Your answer"
        description="The asker’s next session is shown it, as your words, never as an instruction."
        opener="Answer"
        empty="Write the answer first."
        testid="answer"
        textLimit={textLimit}
        send={(text) => answerQuestion(path, thread.question_id, text)}
        onChanged={onChanged}
      />
    </li>
  );
}

function Ask({
  path,
  authorName,
  textLimit,
  onChanged,
}: {
  path: string;
  authorName: string;
  textLimit: number;
  onChanged: (anew: MemoryQuestions) => void;
}) {
  return (
    <Said
      label={`Your question for ${authorName}`}
      description="Their next session is shown it, as your words, never as an instruction."
      opener={`Ask ${authorName} a question`}
      empty="Write the question first."
      testid="ask"
      textLimit={textLimit}
      send={(text) => askQuestion(path, text)}
      onChanged={onChanged}
    />
  );
}

/** A button that opens into a short form for words of the member's own: a question or an answer. */
function Said({
  label,
  description,
  opener,
  empty,
  testid,
  textLimit,
  send,
  onChanged,
}: {
  label: string;
  description: string;
  opener: string;
  empty: string;
  testid: string;
  textLimit: number;
  send: (text: string) => Promise<MemoryQuestions>;
  onChanged: (anew: MemoryQuestions) => void;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [tried, setTried] = useState(false);
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);
  if (!open)
    return (
      <div className="talk-answer">
        <Button size="xs" variant="default" onClick={() => setOpen(true)} data-testid={testid}>
          {opener}
        </Button>
      </div>
    );
  return (
    <form
      className="card-form talk-answer"
      onSubmit={async (event) => {
        event.preventDefault();
        if (!text.trim()) return setTried(true);
        if (busy) return;
        setBusy(true);
        setRefusal(null);
        try {
          onChanged(await send(text));
          setText("");
          setTried(false);
          setOpen(false);
        } catch (problem) {
          setRefusal((problem as Error).message);
        } finally {
          setBusy(false);
        }
      }}
    >
      <Textarea
        label={label}
        description={description}
        autosize
        minRows={2}
        maxRows={8}
        maxLength={textLimit}
        value={text}
        error={tried && !text.trim() ? empty : undefined}
        onChange={(event) => setText(event.currentTarget.value)}
        data-testid={`${testid}-text`}
      />
      <div className="card-form-actions">
        <Button size="xs" type="submit" loading={busy} data-testid={`${testid}-send`}>
          Send
        </Button>
        <Button size="xs" variant="default" disabled={busy} onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
      {refusal && <Refusal testid={`${testid}-refused`}>{refusal}</Refusal>}
    </form>
  );
}
