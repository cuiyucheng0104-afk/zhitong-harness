import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { Context } from '@deepseek-ai/cordis'
import { CredentialProvider } from '@deepseek-ai/dsh-credentials'
import type {
  CredentialInfo,
  CredentialKey,
  CredentialRecord,
  CredentialRecordEntry,
  CredentialRecordInfo,
  CredentialRef,
  ResolvedCredential,
} from '@deepseek-ai/dsh-credentials'
import { ToolCallId } from '@deepseek-ai/dsh-llm'
import SystemPrompt from '@deepseek-ai/dsh-system-prompt'
import ToolRuntime from '@deepseek-ai/dsh-tools'
import type { ToolExecutionResult } from '@deepseek-ai/dsh-tools'

/** In-memory credential provider; record operations are unused by these plugins. */
export class MemoryCredentials extends CredentialProvider {
  readonly values = new Map<string, string>()

  override resolve(ref: CredentialRef): Promise<ResolvedCredential | undefined> {
    const value = this.values.get(ref)
    return Promise.resolve(value === undefined ? undefined : { value, source: 'memory' })
  }

  override describe(ref: CredentialRef): Promise<CredentialInfo> {
    return Promise.resolve({ configured: this.values.has(ref), writable: true })
  }

  override set(ref: CredentialRef, value: string): Promise<void> {
    this.values.set(ref, value)
    return Promise.resolve()
  }

  override unset(ref: CredentialRef): Promise<void> {
    this.values.delete(ref)
    return Promise.resolve()
  }

  override readRecord(_key: CredentialKey): Promise<CredentialRecord | undefined> {
    return Promise.resolve(undefined)
  }

  override describeRecord(_key: CredentialKey): Promise<CredentialRecordInfo> {
    return Promise.resolve({ configured: false, writable: true })
  }

  override listRecords(): Promise<readonly CredentialRecordEntry[]> {
    return Promise.resolve([])
  }

  override modifyRecord(): Promise<CredentialRecord | undefined> {
    return Promise.resolve(undefined)
  }

  override deleteRecord(_key: CredentialKey): Promise<void> {
    return Promise.resolve()
  }
}

/**
 * A context with the tool runtime and, optionally, an in-memory credential store.
 * @param withCredentials - mount {@link MemoryCredentials}.
 * @returns the context and the credential store (when mounted).
 */
export async function toolContext(withCredentials = true): Promise<{ ctx: Context; credentials: MemoryCredentials | undefined }> {
  const ctx = new Context()
  await ctx.plugin(SystemPrompt)
  await ctx.plugin(ToolRuntime)
  if (!withCredentials) return { ctx, credentials: undefined }
  await ctx.plugin(MemoryCredentials)
  return { ctx, credentials: ctx.get('credentials') as MemoryCredentials }
}

let counter = 0

/**
 * Execute one tool call through the registry.
 * @param ctx - context with the tool runtime.
 * @param name - tool name.
 * @param args - tool arguments.
 * @returns the execution result.
 */
export function call(ctx: Context, name: string, args: Record<string, unknown>): Promise<ToolExecutionResult> {
  return ctx.tools.execute({ signal: new AbortController().signal, callId: ToolCallId(`call-${++counter}`), name, arguments: args })
}

/**
 * The text of a result's content.
 * @param result - execution result.
 * @returns concatenated text blocks.
 */
export function text(result: ToolExecutionResult): string {
  return result.content.map(block => (block.type === 'text' ? block.text : '')).join('')
}

/**
 * A successful result's canonical value; fails the test with the error text otherwise.
 * @param result - execution result.
 * @returns the value.
 */
export function valueOf<T>(result: ToolExecutionResult): T {
  if (result.isError) throw new Error(`tool failed: ${text(result)}`)
  return result.value as T
}

/**
 * A fresh temporary directory removed by the returned disposer.
 * @param label - directory name prefix.
 * @returns the path and its cleanup.
 */
export function tempDir(label: string): { path: string; cleanup: () => void } {
  const path = mkdtempSync(join(tmpdir(), `zt-${label}-`))
  return { path, cleanup: () => rmSync(path, { recursive: true, force: true }) }
}
