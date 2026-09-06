import React, { useState, useEffect, useMemo, useRef } from "react";
import {
  Layers,
  Terminal,
  ShieldCheck,
  FlaskConical,
  Server,
  Plus,
  Zap,
  Activity,
  Coins,
  ChevronDown,
  Sparkles,
  Cpu,
  Search,
  Check,
  X,
  BookOpen,
  Shield,
  Flame,
  Puzzle,
  Globe,
  Bot,
  Code2,
  Eye,
  FileText,
  Database,
  Wrench,
  Trash2,
  AlertTriangle,
  type LucideIcon,
} from "lucide-react";
import { useTeamStore, TeamRole, CustomAgentRole } from "./teamStore";
import { useWorkspaceStore } from "../../../stores/workspaceStore";
import { LiquidGlassModelSelector } from "../../../components/ui/LiquidGlassModelSelector";
import { SmartRouterPanel } from "../../smart-router/SmartRouterPanel";

export const LUCIDE_ICON_MAP: Record<string, LucideIcon> = {
  cpu: Cpu,
  book: BookOpen,
  shield: Shield,
  flame: Flame,
  zap: Zap,
  puzzle: Puzzle,
  globe: Globe,
  bot: Bot,
  terminal: Terminal,
  code: Code2,
  search: Search,
  eye: Eye,
  "file-text": FileText,
  database: Database,
  server: Server,
  wrench: Wrench,
};

export const AVAILABLE_ICONS = [
  { id: "bot", label: "Bot", icon: Bot },
  { id: "cpu", label: "CPU", icon: Cpu },
  { id: "code", label: "Code", icon: Code2 },
  { id: "terminal", label: "Terminal", icon: Terminal },
  { id: "shield", label: "Shield", icon: Shield },
  { id: "search", label: "Search", icon: Search },
  { id: "database", label: "Database", icon: Database },
  { id: "server", label: "Server", icon: Server },
  { id: "wrench", label: "Wrench", icon: Wrench },
  { id: "book", label: "Book", icon: BookOpen },
  { id: "flame", label: "Flame", icon: Flame },
  { id: "zap", label: "Zap", icon: Zap },
  { id: "puzzle", label: "Puzzle", icon: Puzzle },
  { id: "globe", label: "Globe", icon: Globe },
  { id: "eye", label: "Eye", icon: Eye },
  { id: "file-text", label: "Doc", icon: FileText },
];

export function getCustomRoleIcon(iconName: string): LucideIcon {
  const clean = (iconName || "").toLowerCase().trim();
  return LUCIDE_ICON_MAP[clean] || Bot;
}

export const PRESET_COLORS = [
  { hex: "#6366f1", name: "Indigo", borderLeft: "border-l-indigo-400", color: "text-indigo-400", bgGlow: "bg-indigo-500/10", borderColor: "border-indigo-500/30" },
  { hex: "#10b981", name: "Emerald", borderLeft: "border-l-emerald-400", color: "text-emerald-400", bgGlow: "bg-emerald-500/10", borderColor: "border-emerald-500/30" },
  { hex: "#f59e0b", name: "Amber", borderLeft: "border-l-amber-400", color: "text-amber-400", bgGlow: "bg-amber-500/10", borderColor: "border-amber-500/30" },
  { hex: "#f43f5e", name: "Rose", borderLeft: "border-l-rose-400", color: "text-rose-400", bgGlow: "bg-rose-500/10", borderColor: "border-rose-500/30" },
  { hex: "#06b6d4", name: "Cyan", borderLeft: "border-l-cyan-400", color: "text-cyan-400", bgGlow: "bg-cyan-500/10", borderColor: "border-cyan-500/30" },
  { hex: "#a855f7", name: "Purple", borderLeft: "border-l-purple-400", color: "text-purple-400", bgGlow: "bg-purple-500/10", borderColor: "border-purple-500/30" },
  { hex: "#d946ef", name: "Fuchsia", borderLeft: "border-l-fuchsia-400", color: "text-fuchsia-400", bgGlow: "bg-fuchsia-500/10", borderColor: "border-fuchsia-500/30" },
  { hex: "#0ea5e9", name: "Sky", borderLeft: "border-l-sky-400", color: "text-sky-400", bgGlow: "bg-sky-500/10", borderColor: "border-sky-500/30" },
  { hex: "#f97316", name: "Orange", borderLeft: "border-l-orange-400", color: "text-orange-400", bgGlow: "bg-orange-500/10", borderColor: "border-orange-500/30" },
  { hex: "#14b8a6", name: "Teal", borderLeft: "border-l-teal-400", color: "text-teal-400", bgGlow: "bg-teal-500/10", borderColor: "border-teal-500/30" },
];

export function getColorConfig(hexColor: string) {
  const clean = (hexColor || "").toLowerCase();
  const match = PRESET_COLORS.find((c) => c.hex.toLowerCase() === clean);
  if (match) return match;
  return {
    hex: hexColor || "#6366f1",
    name: "Custom",
    borderLeft: "border-l-indigo-400",
    color: "text-indigo-400",
    bgGlow: "bg-indigo-500/10",
    borderColor: "border-indigo-500/30",
  };
}

export const SAFE_CUSTOM_TOOLS = [
  { id: "read_file", label: "read_file", category: "File Inspection", description: "Safely view file content" },
  { id: "list_directory", label: "list_directory", category: "File Inspection", description: "List files and subdirectories" },
  { id: "search_code", label: "search_code", category: "File Inspection", description: "Grep and search across codebase" },
  { id: "edit_file", label: "edit_file", category: "File Modification", description: "Propose and edit source code files" },
  { id: "run_test", label: "run_test", category: "Testing & Git", description: "Execute test suite" },
  { id: "git_diff", label: "git_diff", category: "Testing & Git", description: "Inspect git working tree diff" },
  { id: "git_log", label: "git_log", category: "Testing & Git", description: "Read git commit log" },
  { id: "run_command", label: "run_command (allowlisted)", category: "Execution", description: "Safe developer commands (git, npm, npx, pytest, python -m, node)" },
];

interface RoleMetadata {
  role: TeamRole;
  displayName: string;
  description: string;
  icon: LucideIcon;
  color: string;
  borderColor: string;
  borderLeft: string;
  bgGlow: string;
  modelKey: keyof typeof MODEL_KEYS;
  providerKey: keyof typeof PROVIDER_KEYS;
}

const MODEL_KEYS = {
  architect: "architect_model",
  coder: "coder_model",
  reviewer: "reviewer_model",
  tester: "tester_model",
  devops: "devops_model",
} as const;

const PROVIDER_KEYS = {
  architect: "architect_provider",
  coder: "coder_provider",
  reviewer: "reviewer_provider",
  tester: "tester_provider",
  devops: "devops_provider",
} as const;

const ROLES: RoleMetadata[] = [
  {
    role: "architect",
    displayName: "Architect",
    description: "System design, specifications & module decomposition",
    icon: Layers,
    color: "text-purple-400",
    borderColor: "border-purple-500/30",
    borderLeft: "border-l-purple-400",
    bgGlow: "bg-purple-500/10",
    modelKey: "architect",
    providerKey: "architect",
  },
  {
    role: "coder",
    displayName: "Coder",
    description: "Production code generation, refactoring & implementation",
    icon: Terminal,
    color: "text-emerald-400",
    borderColor: "border-emerald-500/30",
    borderLeft: "border-l-emerald-400",
    bgGlow: "bg-emerald-500/10",
    modelKey: "coder",
    providerKey: "coder",
  },
  {
    role: "reviewer",
    displayName: "Reviewer",
    description: "Code audit, security analysis, invariants & PR review",
    icon: ShieldCheck,
    color: "text-amber-400",
    borderColor: "border-amber-500/30",
    borderLeft: "border-l-amber-400",
    bgGlow: "bg-amber-500/10",
    modelKey: "reviewer",
    providerKey: "reviewer",
  },
  {
    role: "tester",
    displayName: "Tester",
    description: "Unit tests, edge cases, chaos checks & verification",
    icon: FlaskConical,
    color: "text-cyan-400",
    borderColor: "border-cyan-500/30",
    borderLeft: "border-l-cyan-400",
    bgGlow: "bg-cyan-500/10",
    modelKey: "tester",
    providerKey: "tester",
  },
  {
    role: "devops",
    displayName: "DevOps",
    description: "Build tooling, dependencies, migrations & deployments",
    icon: Server,
    color: "text-rose-400",
    borderColor: "border-rose-500/30",
    borderLeft: "border-l-rose-400",
    bgGlow: "bg-rose-500/10",
    modelKey: "devops",
    providerKey: "devops",
  },
];

export interface ModelEntry {
  label: string;
  model: string;
  provider: string;
  series: string;
  badge?: string;
  description?: string;
}

export interface ProviderGroup {
  groupName: string;
  providerId: string;
  models: ModelEntry[];
}

export const PROVIDER_GROUPS: ProviderGroup[] = [
  {
    groupName: "Anthropic (Claude)",
    providerId: "anthropic",
    models: [
      // Claude 5 & Fable Series
      { label: "Claude Opus 5 (Frontier Super-Intelligence)", model: "claude-opus-5", provider: "anthropic", series: "Claude 5 & Fable", badge: "Frontier", description: "Next-generation ultimate flagship reasoning model" },
      { label: "Claude Sonnet 5 (Autonomous Agent Flagship)", model: "claude-sonnet-5", provider: "anthropic", series: "Claude 5 & Fable", badge: "Agent", description: "Autonomous long-horizon multi-agent software engineer" },
      { label: "Claude Haiku 5 (Instant High-Throughput)", model: "claude-haiku-5", provider: "anthropic", series: "Claude 5 & Fable", badge: "Fast", description: "Sub-second multi-turn agent response engine" },
      { label: "Claude Fable 5 (Multi-Agent Swarm Specialist)", model: "claude-fable-5", provider: "anthropic", series: "Claude 5 & Fable", badge: "Swarm", description: "Orchestration & distributed multi-agent coordinator" },
      { label: "Claude Fable (Autonomous Reasoning Agent)", model: "claude-fable", provider: "anthropic", series: "Claude 5 & Fable", badge: "Agentic", description: "Specialized for open-ended coding tasks" },

      // Claude Opus Series
      { label: "Claude Opus 4.8 (Ultra-Reasoning Deep Proofs)", model: "claude-opus-4.8", provider: "anthropic", series: "Claude Opus Series", badge: "Reasoning", description: "Mathematical invariants & complex architecture analysis" },
      { label: "Claude Opus 4.7 (Large Context Architecture)", model: "claude-opus-4.7", provider: "anthropic", series: "Claude Opus Series", badge: "Arch", description: "Deep repo-level decomposition and security audits" },
      { label: "Claude Opus 4.6 (Complex Code Synthesis)", model: "claude-opus-4.6", provider: "anthropic", series: "Claude Opus Series", badge: "Synthesis", description: "Massive code generation & refactoring across modules" },
      { label: "Claude Opus 4.0 (Frontier Reasoning)", model: "claude-opus-4", provider: "anthropic", series: "Claude Opus Series", badge: "Opus 4", description: "Heavy analytical computing and formal logic" },
      { label: "Claude 3 Opus (Foundational Analysis)", model: "claude-3-opus-latest", provider: "anthropic", series: "Claude Opus Series", badge: "Opus 3", description: "Foundational flagship analytical reasoning model" },

      // Claude Sonnet Series
      { label: "Claude 3.7 Sonnet (Hybrid Reasoning & Code)", model: "claude-3-7-sonnet-latest", provider: "anthropic", series: "Claude Sonnet Series", badge: "Hybrid 200K", description: "State-of-the-art hybrid thinking & deterministic code" },
      { label: "Claude Sonnet 4.5 (Frontier Coding Specialist)", model: "claude-sonnet-4.5", provider: "anthropic", series: "Claude Sonnet Series", badge: "Coding", description: "Next-generation precision coding and debugging engine" },
      { label: "Claude 3.5 Sonnet v2 (Benchmark Flagship)", model: "claude-3-5-sonnet-latest", provider: "anthropic", series: "Claude Sonnet Series", badge: "Flagship", description: "Industry benchmark for software engineering & tools" },
      { label: "Claude 3.5 Sonnet v1 (Reliable Agentic)", model: "claude-3-5-sonnet-20240620", provider: "anthropic", series: "Claude Sonnet Series", badge: "Stable", description: "First-generation high precision coding benchmark" },

      // Claude Haiku Series
      { label: "Claude 3.5 Haiku (Fast & Agentic)", model: "claude-3-5-haiku-latest", provider: "anthropic", series: "Claude Haiku Series", badge: "Fast", description: "Rapid tool calling, file analysis & verification" },
      { label: "Claude 3 Haiku (Lightweight Fast)", model: "claude-3-haiku-20240307", provider: "anthropic", series: "Claude Haiku Series", badge: "Light", description: "Ultra-fast triage, linting, and simple repairs" },
    ],
  },
  {
    groupName: "OpenAI",
    providerId: "openai",
    models: [
      // GPT-5 & Beyond Series
      { label: "GPT-5.6 (Omni-Architect Supercomputer)", model: "gpt-5.6", provider: "openai", series: "GPT-5 & Next-Gen", badge: "Frontier", description: "Highest capability frontier autonomous architect model" },
      { label: "GPT-5.5 (Frontier Reasoning & Agentic)", model: "gpt-5.5", provider: "openai", series: "GPT-5 & Next-Gen", badge: "Agentic", description: "Autonomous full-stack engineering and planning" },
      { label: "GPT-5 Turbo (Accelerated Multi-Modal)", model: "gpt-5-turbo", provider: "openai", series: "GPT-5 & Next-Gen", badge: "Turbo", description: "Fast, high-throughput GPT-5 frontier variant" },
      { label: "GPT-5 Base (Foundation)", model: "gpt-5", provider: "openai", series: "GPT-5 & Next-Gen", badge: "Base", description: "Frontier foundation model for complex reasoning" },

      // Project Terra / Luna / Sol Series
      { label: "OpenAI Terra (Planetary-Scale Reasoning)", model: "terra-1", provider: "openai", series: "Terra / Luna / Sol", badge: "Terra", description: "Large-scale systems engineering & infrastructure logic" },
      { label: "OpenAI Luna (Ultra-Low Latency Edge)", model: "luna-1", provider: "openai", series: "Terra / Luna / Sol", badge: "Luna", description: "Sub-10ms edge reasoning and interactive streaming" },
      { label: "OpenAI Sol (Scientific & High-Compute)", model: "sol-1", provider: "openai", series: "Terra / Luna / Sol", badge: "Sol", description: "High-compute mathematical synthesis & optimization" },

      // Reasoning (o-Series)
      { label: "OpenAI o3 (Frontier Reasoning Master)", model: "o3", provider: "openai", series: "Reasoning o-Series", badge: "Frontier Thinking", description: "Maximum depth chain-of-thought for hard engineering" },
      { label: "o3-mini (High-Speed Deep Reasoning)", model: "o3-mini", provider: "openai", series: "Reasoning o-Series", badge: "Fast CoT", description: "Code & math specialist with adjustable reasoning effort" },
      { label: "o3-high (Maximum Compute Thinking)", model: "o3-high", provider: "openai", series: "Reasoning o-Series", badge: "Max Compute", description: "Exhaustive exploration of architectural edge cases" },
      { label: "OpenAI o1 (Full Chain-of-Thought)", model: "o1", provider: "openai", series: "Reasoning o-Series", badge: "Deep CoT", description: "Complex scientific reasoning and algorithm design" },
      { label: "o1-pro (Compute-Intensive Reasoning)", model: "o1-pro", provider: "openai", series: "Reasoning o-Series", badge: "Pro", description: "Heavy inference compute for complex refactoring" },
      { label: "o1-mini (Code & Math Specialist)", model: "o1-mini", provider: "openai", series: "Reasoning o-Series", badge: "Code", description: "Fast STEM & code synthesis engine" },

      // GPT-4o Series
      { label: "GPT-4o (Multimodal Flagship)", model: "gpt-4o", provider: "openai", series: "GPT-4o Series", badge: "128K Flagship", description: "General intelligence workhorse for all software tasks" },
      { label: "GPT-4o Mini (High-Speed Lightweight)", model: "gpt-4o-mini", provider: "openai", series: "GPT-4o Series", badge: "Fast 128K", description: "Fast, cost-efficient for testing, linting and doc generation" },
      { label: "GPT-4.5 Preview (Expanded Context)", model: "gpt-4.5-preview", provider: "openai", series: "GPT-4o Series", badge: "Preview", description: "Expanded real-world knowledge & nuance" },
      { label: "ChatGPT-4o Latest (Dynamic Live)", model: "chatgpt-4o-latest", provider: "openai", series: "GPT-4o Series", badge: "Latest", description: "Continuous rolling snapshot of ChatGPT flagship" },
      { label: "GPT-4o Realtime Preview (Low Latency)", model: "gpt-4o-realtime-preview", provider: "openai", series: "GPT-4o Series", badge: "Realtime", description: "Ultra-low latency duplex interaction" },
    ],
  },
  {
    groupName: "NVIDIA NIM",
    providerId: "nvidia",
    models: [
      // MiniMax Series
      { label: "MiniMax M3 (Long-Context Reasoning Agent)", model: "minimax/minimax-m3", provider: "nvidia", series: "MiniMax Series", badge: "M3 Reasoning", description: "State-of-the-art agentic reasoning and tool execution" },
      { label: "MiniMax M2 (High-Speed Execution)", model: "minimax/minimax-m2", provider: "nvidia", series: "MiniMax Series", badge: "M2 Fast", description: "High-throughput code generation and test execution" },
      { label: "MiniMax Text-01 (4M Token Context)", model: "minimax/minimax-text-01", provider: "nvidia", series: "MiniMax Series", badge: "4M Context", description: "Massive multi-repo context ingestion on NVIDIA NIM" },

      // Nemotron & DeepSeek on NIM
      { label: "DeepSeek R1 (NVIDIA NIM Hosted)", model: "deepseek-ai/deepseek-r1", provider: "nvidia", series: "Nemotron & DeepSeek", badge: "R1 NIM", description: "DeepSeek R1 with TensorRT-LLM hardware acceleration" },
      { label: "Llama 3.1 Nemotron 70B (Reward-Aligned)", model: "nvidia/llama-3.1-nemotron-70b-instruct", provider: "nvidia", series: "Nemotron & DeepSeek", badge: "Aligned", description: "High accuracy RLHF alignment for instruction following" },
      { label: "Nemotron-4 340B (Supercomputer Scale)", model: "nvidia/nemotron-4-340b-instruct", provider: "nvidia", series: "Nemotron & DeepSeek", badge: "340B", description: "NVIDIA enterprise flagship for synthetic data & coding" },

      // Meta Llama on NIM
      { label: "Llama 3.3 70B Instruct (NIM Throughput)", model: "meta/llama-3.3-70b-instruct", provider: "nvidia", series: "Meta Llama on NIM", badge: "70B NIM", description: "Fast TensorRT-optimized 70B model" },
      { label: "Llama 3.1 405B Instruct (Frontier NIM)", model: "meta/llama-3.1-405b-instruct", provider: "nvidia", series: "Meta Llama on NIM", badge: "405B NIM", description: "Largest open-weights foundation model on NIM cluster" },
    ],
  },
  {
    groupName: "Google Gemini",
    providerId: "gemini",
    models: [
      // Gemini 2.5 Series
      { label: "Gemini 2.5 Pro (2M Reasoning & Code Flagship)", model: "gemini-2.5-pro", provider: "gemini", series: "Gemini 2.5 Series", badge: "2M Flagship", description: "Extreme long-context reasoning, code review, and synthesis" },
      { label: "Gemini 2.5 Flash (1M Thinking Flash)", model: "gemini-2.5-flash", provider: "gemini", series: "Gemini 2.5 Series", badge: "1M Flash", description: "Next-generation lightweight thinking model with high speed" },

      // Gemini 2.0 Series
      { label: "Gemini 2.0 Flash (Ultra-Fast 1M)", model: "gemini-2.0-flash", provider: "gemini", series: "Gemini 2.0 Series", badge: "1M Speed", description: "Sub-second multi-turn coding and tool manipulation" },
      { label: "Gemini 2.0 Flash Thinking Exp (Realtime CoT)", model: "gemini-2.0-flash-thinking-exp", provider: "gemini", series: "Gemini 2.0 Series", badge: "Thinking", description: "Explicit chain-of-thought reasoning before tool execution" },
      { label: "Gemini 2.0 Pro Experimental (Frontier Benchmark)", model: "gemini-2.0-pro-exp-02-05", provider: "gemini", series: "Gemini 2.0 Series", badge: "Pro Exp", description: "Competitive with top frontier models on code generation" },

      // Gemini 1.5 Series
      { label: "Gemini 1.5 Pro (2M Long Context Workhorse)", model: "gemini-1.5-pro", provider: "gemini", series: "Gemini 1.5 Series", badge: "2M Context", description: "Full codebase ingestion and architecture mapping" },
      { label: "Gemini 1.5 Flash (Sub-Second Fast)", model: "gemini-1.5-flash", provider: "gemini", series: "Gemini 1.5 Series", badge: "Flash", description: "Fast, cost-efficient for testing and quick fixes" },
    ],
  },
  {
    groupName: "xAI (Grok)",
    providerId: "xai",
    models: [
      { label: "Grok 3 (Frontier Reasoning & Real-Time Synthesis)", model: "grok-3", provider: "xai", series: "Grok 3 Series", badge: "Frontier", description: "Next-generation flagship reasoning & software architecture" },
      { label: "Grok 3 Mini (Speed-Optimized Reasoning)", model: "grok-3-mini", provider: "xai", series: "Grok 3 Series", badge: "Fast", description: "Rapid inference reasoning engine for autonomous loops" },
      { label: "Grok 2 (1212 Flagship Code)", model: "grok-2-1212", provider: "xai", series: "Grok 2 Series", badge: "Grok 2", description: "State-of-the-art vision and code execution" },
      { label: "Grok 2 Vision (Visual Understanding)", model: "grok-2-vision-1212", provider: "xai", series: "Grok 2 Series", badge: "Vision", description: "UI mockup to code synthesis and screenshot audit" },
      { label: "Grok Beta (Unfiltered Research)", model: "grok-beta", provider: "xai", series: "Grok 2 Series", badge: "Beta", description: "Early access research model" },
    ],
  },
  {
    groupName: "DeepSeek",
    providerId: "deepseek",
    models: [
      { label: "DeepSeek R1 (Open Frontier Reasoning)", model: "deepseek-reasoner", provider: "deepseek", series: "DeepSeek Reasoning", badge: "R1 CoT", description: "Open frontier reasoning matching top proprietary models" },
      { label: "DeepSeek V3 (671B MoE Chat)", model: "deepseek-chat", provider: "deepseek", series: "DeepSeek MoE", badge: "V3 MoE", description: "Ultra-efficient 671B mixture-of-experts model" },
      { label: "DeepSeek Coder V2 (236B Code Specialist)", model: "deepseek-coder-v2", provider: "deepseek", series: "DeepSeek Coder", badge: "Coder 236B", description: "Specialized for 338 programming languages and tests" },
    ],
  },
  {
    groupName: "Mistral AI",
    providerId: "mistral",
    models: [
      { label: "Mistral Large 2 (128K Flagship)", model: "mistral-large-2411", provider: "mistral", series: "Mistral Large", badge: "128K Flagship", description: "Top-tier multilingual code generation and formal reasoning" },
      { label: "Codestral 2501 (Code Specialist)", model: "codestral-2501", provider: "mistral", series: "Codestral", badge: "Code", description: "Dedicated 80+ programming language master" },
      { label: "Pixtral Large 124B (Multimodal)", model: "pixtral-large-2411", provider: "mistral", series: "Pixtral", badge: "124B Vision", description: "Multimodal frontier vision & diagram analysis" },
      { label: "Mistral Small (Fast Enterprise)", model: "mistral-small-2409", provider: "mistral", series: "Mistral Small", badge: "Small", description: "Low-latency enterprise code assistant" },
      { label: "Ministral 8B (Edge Fast)", model: "ministral-8b", provider: "mistral", series: "Ministral Edge", badge: "8B Edge", description: "Ultra-fast low-resource edge model" },
    ],
  },
  {
    groupName: "Groq (LPU Ultra-Speed)",
    providerId: "groq",
    models: [
      { label: "Llama 3.3 70B Versatile (300+ tok/s)", model: "llama-3.3-70b-versatile", provider: "groq", series: "Groq LPU Speed", badge: "300 tok/s", description: "Instant feedback for code generation and test runs" },
      { label: "Llama 3.1 8B Instant (750+ tok/s)", model: "llama-3.1-8b-instant", provider: "groq", series: "Groq LPU Speed", badge: "750 tok/s", description: "World-record low latency for DevOps and linting" },
      { label: "DeepSeek R1 Distill 70B (Groq Reasoning)", model: "deepseek-r1-distill-llama-70b", provider: "groq", series: "Groq LPU Reasoning", badge: "R1 Groq", description: "Instantaneous deep chain-of-thought on Groq LPUs" },
      { label: "Mixtral 8x7B (Fast MoE)", model: "mixtral-8x7b-32768", provider: "groq", series: "Groq MoE", badge: "32K MoE", description: "High-throughput mixture of experts" },
    ],
  },
  {
    groupName: "OpenRouter (Multi-Gateway)",
    providerId: "openrouter",
    models: [
      { label: "Claude 3.7 Sonnet (via OpenRouter)", model: "anthropic/claude-3.7-sonnet", provider: "openrouter", series: "OpenRouter Multi", badge: "Sonnet 3.7", description: "Universal routing to Claude 3.7 Sonnet" },
      { label: "Claude Opus 4 (via OpenRouter)", model: "anthropic/claude-opus-4", provider: "openrouter", series: "OpenRouter Multi", badge: "Opus 4", description: "Universal routing to Claude Opus 4" },
      { label: "OpenAI o3-mini (via OpenRouter)", model: "openai/o3-mini", provider: "openrouter", series: "OpenRouter Multi", badge: "o3-mini", description: "Fast reasoning gateway" },
      { label: "DeepSeek R1 (via OpenRouter)", model: "deepseek/deepseek-r1", provider: "openrouter", series: "OpenRouter Multi", badge: "R1 Gateway", description: "Direct deep reasoning gateway" },
      { label: "MiniMax Text-01 (via OpenRouter)", model: "minimax/minimax-text-01", provider: "openrouter", series: "OpenRouter Multi", badge: "4M Context", description: "MiniMax 4M token context gateway" },
      { label: "Llama 3.3 70B (via OpenRouter)", model: "meta-llama/llama-3.3-70b-instruct", provider: "openrouter", series: "OpenRouter Multi", badge: "Llama 3.3", description: "Open weights gateway" },
    ],
  },
  {
    groupName: "Ollama (Local Offline Private)",
    providerId: "ollama",
    models: [
      { label: "DeepSeek R1 70B (Local Reasoning)", model: "deepseek-r1:70b", provider: "ollama", series: "Local Offline", badge: "Local 70B", description: "100% private local frontier reasoning on workstation GPU" },
      { label: "DeepSeek R1 8B (Local Fast)", model: "deepseek-r1:8b", provider: "ollama", series: "Local Offline", badge: "Local 8B", description: "Lightweight local reasoning for consumer GPUs" },
      { label: "Llama 3.3 70B (Local Meta Flagship)", model: "llama3.3:70b", provider: "ollama", series: "Local Offline", badge: "Local Flagship", description: "Full capability offline coding and architecture" },
      { label: "Qwen 2.5 Coder 32B (Local Code Specialist)", model: "qwen2.5-coder:32b", provider: "ollama", series: "Local Offline", badge: "Code 32B", description: "High-performance offline coding champion" },
      { label: "Microsoft Phi-4 14B (Local Reasoning)", model: "phi4:14b", provider: "ollama", series: "Local Offline", badge: "Phi-4", description: "Small footprint, high reasoning capability" },
      { label: "Mistral 7B (Local Lightweight)", model: "mistral:latest", provider: "ollama", series: "Local Offline", badge: "Mistral", description: "Low memory usage local model" },
    ],
  },
  {
    groupName: "Cohere",
    providerId: "cohere",
    models: [
      { label: "Command A (256K Enterprise Workhorse)", model: "command-a-03-2025", provider: "cohere", series: "Cohere Enterprise", badge: "256K Enterprise", description: "High-throughput enterprise reasoning and task automation" },
      { label: "Command R+ (128K Agent Flagship)", model: "command-r-plus-08-2024", provider: "cohere", series: "Cohere Enterprise", badge: "128K Agent", description: "Best-in-class multi-step agent tool calling" },
      { label: "Command R (Enterprise RAG)", model: "command-r-08-2024", provider: "cohere", series: "Cohere Enterprise", badge: "RAG Fast", description: "Fast context retrieval and verification" },
    ],
  },
];

interface ModelPricing {
  inputPerMillion: number;
  outputPerMillion: number;
}

const MODEL_PRICING: Record<string, ModelPricing> = {
  // Anthropic
  "claude-opus-5": { inputPerMillion: 15.00, outputPerMillion: 75.00 },
  "claude-sonnet-5": { inputPerMillion: 3.50, outputPerMillion: 17.50 },
  "claude-haiku-5": { inputPerMillion: 1.00, outputPerMillion: 5.00 },
  "claude-fable": { inputPerMillion: 3.00, outputPerMillion: 15.00 },
  "claude-opus-4.8": { inputPerMillion: 15.00, outputPerMillion: 75.00 },
  "claude-opus-4.7": { inputPerMillion: 15.00, outputPerMillion: 75.00 },
  "claude-opus-4.6": { inputPerMillion: 15.00, outputPerMillion: 75.00 },
  "claude-opus-4": { inputPerMillion: 15.00, outputPerMillion: 75.00 },
  "claude-3-opus": { inputPerMillion: 15.00, outputPerMillion: 75.00 },
  "claude-3-7-sonnet": { inputPerMillion: 3.00, outputPerMillion: 15.00 },
  "claude-sonnet-4.5": { inputPerMillion: 3.00, outputPerMillion: 15.00 },
  "claude-3-5-sonnet": { inputPerMillion: 3.00, outputPerMillion: 15.00 },
  "claude-3-5-haiku": { inputPerMillion: 0.80, outputPerMillion: 4.00 },
  // OpenAI
  "gpt-5.6": { inputPerMillion: 5.00, outputPerMillion: 20.00 },
  "gpt-5.5": { inputPerMillion: 4.00, outputPerMillion: 16.00 },
  "gpt-5": { inputPerMillion: 3.00, outputPerMillion: 12.00 },
  "terra-1": { inputPerMillion: 3.00, outputPerMillion: 12.00 },
  "luna-1": { inputPerMillion: 0.50, outputPerMillion: 2.00 },
  "sol-1": { inputPerMillion: 5.00, outputPerMillion: 25.00 },
  "o3": { inputPerMillion: 5.00, outputPerMillion: 20.00 },
  "o3-mini": { inputPerMillion: 1.10, outputPerMillion: 4.40 },
  "o1": { inputPerMillion: 15.00, outputPerMillion: 60.00 },
  "gpt-4o": { inputPerMillion: 2.50, outputPerMillion: 10.00 },
  "gpt-4o-mini": { inputPerMillion: 0.15, outputPerMillion: 0.60 },
  // NVIDIA NIM & MiniMax
  "minimax": { inputPerMillion: 0.20, outputPerMillion: 1.10 },
  "nemotron": { inputPerMillion: 0.70, outputPerMillion: 0.90 },
  // Gemini
  "gemini-2.5-pro": { inputPerMillion: 1.25, outputPerMillion: 5.00 },
  "gemini-2.5-flash": { inputPerMillion: 0.075, outputPerMillion: 0.30 },
  // xAI Grok
  "grok-3": { inputPerMillion: 3.00, outputPerMillion: 15.00 },
  "grok-2": { inputPerMillion: 2.00, outputPerMillion: 10.00 },
  // DeepSeek
  "deepseek-reasoner": { inputPerMillion: 0.55, outputPerMillion: 2.19 },
  "deepseek-chat": { inputPerMillion: 0.14, outputPerMillion: 0.28 },
  // Groq
  "llama-3.3-70b": { inputPerMillion: 0.59, outputPerMillion: 0.79 },
  "llama-3.1-8b": { inputPerMillion: 0.05, outputPerMillion: 0.08 },
  // Auto
  "auto": { inputPerMillion: 1.00, outputPerMillion: 4.00 },
};

function getPricingForModel(model: string): ModelPricing {
  const m = model.toLowerCase();
  for (const [key, p] of Object.entries(MODEL_PRICING)) {
    if (m.includes(key) || key.includes(m)) return p;
  }
  return { inputPerMillion: 2.50, outputPerMillion: 10.00 };
}

export function getProviderBadgeColor(provider: string): string {
  const p = (provider || "").toLowerCase();
  if (p.includes("anthropic")) return "bg-purple-500/15 text-purple-300 border border-purple-500/30";
  if (p.includes("openai")) return "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30";
  if (p.includes("nvidia")) return "bg-lime-500/15 text-lime-300 border border-lime-500/30";
  if (p.includes("gemini")) return "bg-sky-500/15 text-sky-300 border border-sky-500/30";
  if (p.includes("xai")) return "bg-amber-500/15 text-amber-300 border border-amber-500/30";
  if (p.includes("deepseek")) return "bg-cyan-500/15 text-cyan-300 border border-cyan-500/30";
  if (p.includes("groq")) return "bg-orange-500/15 text-orange-300 border border-orange-500/30";
  if (p.includes("mistral")) return "bg-rose-500/15 text-rose-300 border border-rose-500/30";
  if (p.includes("ollama")) return "bg-teal-500/15 text-teal-300 border border-teal-500/30";
  if (p.includes("openrouter")) return "bg-indigo-500/15 text-indigo-300 border border-indigo-500/30";
  if (p.includes("cohere")) return "bg-blue-500/15 text-blue-300 border border-blue-500/30";
  return "bg-white/10 text-on-surface-variant border border-white/10";
}

const CUSTOM_MODELS_KEY = "code_os_user_custom_models";

interface AgentModelDropdownProps {
  roleMeta: RoleMetadata;
  activeModel: string;
  activeProvider: string;
  isAuto: boolean;
  disabled: boolean;
  userCustomModels: ModelEntry[];
  onSelect: (provider: string, model: string) => void;
  onOpenCustomModal: () => void;
  onSelectAuto: () => void;
}

const AgentModelDropdown: React.FC<AgentModelDropdownProps> = ({
  roleMeta,
  activeModel,
  activeProvider,
  isAuto,
  disabled,
  userCustomModels,
  onSelect,
  onOpenCustomModal,
  onSelectAuto,
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [selectedTab, setSelectedTab] = useState("all");

  const RoleIcon = roleMeta.icon;

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setIsOpen(false);
    };
    if (isOpen) {
      document.addEventListener("keydown", handleKey);
      document.body.style.overflow = "hidden";
    }
    return () => {
      document.removeEventListener("keydown", handleKey);
      document.body.style.overflow = "";
    };
  }, [isOpen]);

  const allModelsFlat = useMemo(() => {
    const list: ModelEntry[] = [...userCustomModels];
    PROVIDER_GROUPS.forEach((g) => {
      g.models.forEach((m) => list.push(m));
    });
    return list;
  }, [userCustomModels]);

  const currentMatch = useMemo(() => {
    return (
      allModelsFlat.find(
        (m: ModelEntry) =>
          m.model.toLowerCase() === activeModel.toLowerCase() &&
          (m.provider.toLowerCase() === activeProvider.toLowerCase() || !activeProvider)
      ) || allModelsFlat.find((m: ModelEntry) => m.model.toLowerCase() === activeModel.toLowerCase())
    );
  }, [allModelsFlat, activeModel, activeProvider]);

  const filteredGroups = useMemo(() => {
    const q = search.trim().toLowerCase();
    const groups: { groupName: string; providerId: string; seriesMap: Map<string, ModelEntry[]> }[] = [];

    // Custom models first
    if (userCustomModels.length > 0 && (selectedTab === "all" || selectedTab === "custom")) {
      const matchedCustom = userCustomModels.filter(
        (m: ModelEntry) => !q || m.label.toLowerCase().includes(q) || m.model.toLowerCase().includes(q)
      );
      if (matchedCustom.length > 0) {
        const smap = new Map<string, ModelEntry[]>();
        smap.set("User Custom", matchedCustom);
        groups.push({
          groupName: "⭐ Custom User Models",
          providerId: "custom",
          seriesMap: smap,
        });
      }
    }

    PROVIDER_GROUPS.forEach((group) => {
      if (selectedTab !== "all" && group.providerId !== selectedTab) return;

      const matched = group.models.filter((m) => {
        if (!q) return true;
        return (
          m.label.toLowerCase().includes(q) ||
          m.model.toLowerCase().includes(q) ||
          m.series.toLowerCase().includes(q) ||
          (m.badge && m.badge.toLowerCase().includes(q)) ||
          (m.description && m.description.toLowerCase().includes(q))
        );
      });

      if (matched.length > 0) {
        const smap = new Map<string, ModelEntry[]>();
        matched.forEach((m) => {
          const s = m.series || group.groupName;
          if (!smap.has(s)) smap.set(s, []);
          smap.get(s)!.push(m);
        });
        groups.push({
          groupName: group.groupName,
          providerId: group.providerId,
          seriesMap: smap,
        });
      }
    });

    return groups;
  }, [search, selectedTab, userCustomModels]);

  const TABS = [
    { id: "all", label: "All Models" },
    { id: "anthropic", label: "Anthropic Claude" },
    { id: "openai", label: "OpenAI" },
    { id: "nvidia", label: "NVIDIA NIM" },
    { id: "gemini", label: "Google Gemini" },
    { id: "xai", label: "xAI Grok" },
    { id: "deepseek", label: "DeepSeek" },
    { id: "mistral", label: "Mistral" },
    { id: "groq", label: "Groq LPU" },
    { id: "openrouter", label: "OpenRouter" },
    { id: "ollama", label: "Local (Ollama)" },
    { id: "cohere", label: "Cohere" },
  ];

  return (
    <div className="relative w-full min-w-0">
      {/* Hidden Accessible Select for Test / Automation compatibility */}
      <select
        data-testid={`model-select-${roleMeta.role}`}
        value={isAuto ? "auto:auto" : `${activeProvider}:${activeModel}`}
        onChange={(e) => {
          const val = e.target.value;
          if (val === "__custom__") {
            onOpenCustomModal();
            return;
          }
          if (val === "auto:auto") {
            onSelectAuto();
            return;
          }
          const [p, m] = val.split(":");
          onSelect(p, m);
        }}
        disabled={disabled}
        className="sr-only"
        tabIndex={-1}
        aria-hidden="true"
      >
        <option value="auto:auto">⚡ Auto (Dynamic Task Difficulty Routing)</option>
        {allModelsFlat.map((m) => (
          <option key={`${m.provider}:${m.model}`} value={`${m.provider}:${m.model}`}>
            {m.label} ({m.provider})
          </option>
        ))}
      </select>

      {/* Styled Glassmorphic Trigger Button */}
      <button
        type="button"
        disabled={disabled}
        onClick={() => setIsOpen(true)}
        className={`w-full flex items-center justify-between gap-2 px-3 py-2 rounded-lg border text-left text-xs transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed group shadow-xs ${
          isAuto
            ? "bg-primary-container/10 hover:bg-primary-container/15 border-primary-container/40 text-primary-container hover:shadow-[0_0_12px_rgba(0,218,243,0.15)]"
            : "bg-[#141622]/90 hover:bg-[#1a1d2c] border-white/10 hover:border-primary/40 text-white hover:shadow-[0_0_12px_rgba(0,218,243,0.12)]"
        }`}
      >
        <div className="flex items-center gap-2 min-w-0 flex-1 overflow-hidden">
          {isAuto ? (
            <>
              <Sparkles size={13} className="text-primary-container shrink-0 animate-pulse" />
              <span className="truncate font-semibold text-primary-container tracking-tight">
                ⚡ Auto (Difficulty Routing)
              </span>
            </>
          ) : (
            <>
              <span className="w-2 h-2 rounded-full bg-emerald-400 shrink-0 shadow-[0_0_6px_rgba(52,211,153,0.8)]" />
              <span className="truncate font-semibold text-white/90 group-hover:text-white transition-colors tracking-tight">
                {currentMatch ? currentMatch.label : activeModel}
              </span>
            </>
          )}
        </div>

        <div className="flex items-center gap-1.5 shrink-0">
          {!isAuto && (
            <span className={`text-[9.5px] font-semibold px-2 py-0.5 rounded-md uppercase tracking-wider ${getProviderBadgeColor(activeProvider)}`}>
              {activeProvider}
            </span>
          )}
          <ChevronDown
            size={13}
            className="text-white/40 group-hover:text-primary transition-transform group-hover:translate-y-0.5 shrink-0"
          />
        </div>
      </button>

      {/* Centered Command Palette Modal Hub */}
      {isOpen && (
        <div
          className="fixed inset-0 z-[9999] bg-black/80 backdrop-blur-md flex items-center justify-center p-3 sm:p-6 animate-in fade-in duration-150"
          onClick={(e) => {
            if (e.target === e.currentTarget) setIsOpen(false);
          }}
        >
          <div
            className="w-full max-w-3xl bg-[#111216] border border-white/15 rounded-2xl shadow-[0_32px_96px_rgba(0,0,0,0.95)] flex flex-col max-h-[88vh] overflow-hidden animate-in zoom-in-95 duration-150"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div className="p-4 px-5 border-b border-white/10 bg-surface-container-lowest/90 flex items-center justify-between gap-3 shrink-0">
              <div className="flex items-center gap-3 min-w-0">
                <div className={`w-9 h-9 rounded-xl ${roleMeta.bgGlow} border ${roleMeta.borderColor} flex items-center justify-center shrink-0`}>
                  <RoleIcon size={18} className={roleMeta.color} />
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <h3 className="text-sm font-bold text-on-surface truncate">
                      Select Model for {roleMeta.displayName}
                    </h3>
                    <span className="text-[11px] font-mono text-on-surface-variant/70">
                      @{roleMeta.role}
                    </span>
                    {isAuto ? (
                      <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-primary-container/20 text-primary-container border border-primary-container/30 flex items-center gap-1 font-semibold">
                        <Sparkles size={10} /> Auto Routing
                      </span>
                    ) : (
                      <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-white/5 border border-white/10 text-on-surface-variant truncate max-w-[200px]">
                        Current: {currentMatch ? currentMatch.label.split(" (")[0] : activeModel}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-on-surface-variant truncate mt-0.5">
                    {roleMeta.description}
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2 shrink-0">
                <span className="hidden sm:inline-flex items-center px-2 py-0.5 rounded text-[10px] font-mono bg-white/5 border border-white/10 text-on-surface-variant">
                  ESC to close
                </span>
                <button
                  type="button"
                  onClick={() => setIsOpen(false)}
                  className="w-8 h-8 rounded-lg hover:bg-white/10 text-on-surface-variant hover:text-on-surface flex items-center justify-center transition-colors cursor-pointer"
                >
                  <X size={16} />
                </button>
              </div>
            </div>

            {/* Search Input Bar */}
            <div className="p-3 px-5 border-b border-white/10 bg-surface-container-low/40 flex items-center gap-2.5 shrink-0">
              <Search size={16} className="text-on-surface-variant shrink-0 ml-1" />
              <input
                type="text"
                autoFocus
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search 75+ frontier models (Opus 5, GPT-5.6, MiniMax M3, Grok 3, Sol, o3)..."
                className="w-full bg-transparent text-xs text-on-surface placeholder:text-on-surface-variant/50 focus:outline-none font-mono py-1"
              />
              {search && (
                <button
                  type="button"
                  onClick={() => setSearch("")}
                  className="text-on-surface-variant hover:text-on-surface p-1 text-xs rounded hover:bg-white/5 cursor-pointer"
                >
                  <X size={14} />
                </button>
              )}
            </div>

            {/* Quick Filter Provider Tabs */}
            <div className="flex items-center gap-1.5 px-5 py-2.5 border-b border-white/10 bg-surface-container-low/20 overflow-x-auto custom-scrollbar shrink-0">
              {TABS.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => setSelectedTab(t.id)}
                  className={`px-3 py-1 rounded-lg text-[11px] font-mono whitespace-nowrap transition-all cursor-pointer shrink-0 flex items-center gap-1.5 ${
                    selectedTab === t.id
                      ? "bg-primary-container text-on-primary-container font-semibold shadow-xs"
                      : "bg-surface-container/60 hover:bg-surface-container text-on-surface-variant hover:text-on-surface border border-white/5"
                  }`}
                >
                  <span>{t.label}</span>
                </button>
              ))}
            </div>

            {/* Dynamic Auto-Routing Spotlight Card */}
            <div className="p-3 px-5 border-b border-white/5 bg-gradient-to-r from-primary-container/10 via-surface-container/30 to-transparent shrink-0">
              <button
                type="button"
                onClick={() => {
                  onSelectAuto();
                  setIsOpen(false);
                }}
                className={`w-full flex items-center justify-between p-3 rounded-xl border text-left transition-all cursor-pointer ${
                  isAuto
                    ? "bg-primary-container/20 border-primary-container/50 shadow-md ring-1 ring-primary-container/30"
                    : "bg-surface-container/70 hover:bg-surface-container border-primary-container/20 hover:border-primary-container/40"
                }`}
              >
                <div className="flex items-center gap-3 min-w-0">
                  <div className="w-8 h-8 rounded-lg bg-primary-container/20 border border-primary-container/30 flex items-center justify-center shrink-0">
                    <Sparkles size={16} className="text-primary-container animate-pulse" />
                  </div>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-bold text-primary-container">
                        ⚡ Auto (Dynamic Task Difficulty Routing)
                      </span>
                      <span className="text-[9px] px-1.5 py-0.2 rounded font-mono bg-primary-container/20 text-primary-container border border-primary-container/30 font-semibold">
                        Intelligent
                      </span>
                    </div>
                    <p className="text-[11px] text-on-surface-variant mt-0.5">
                      Automatically routes complex architectural & reasoning steps to frontier flagships (Opus 5 / o3 / GPT-5.6) and rapid subtasks to fast models
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0 ml-3">
                  {isAuto ? (
                    <span className="flex items-center gap-1 text-[11px] font-mono text-primary-container font-semibold bg-primary-container/20 px-2.5 py-1 rounded-md">
                      <Check size={13} /> Active
                    </span>
                  ) : (
                    <span className="text-[11px] font-mono text-on-surface-variant hover:text-primary-container bg-white/5 hover:bg-white/10 px-2.5 py-1 rounded-md border border-white/10 transition-colors">
                      Enable Auto
                    </span>
                  )}
                </div>
              </button>
            </div>

            {/* Scrollable Model List */}
            <div className="flex-1 overflow-y-auto p-4 px-5 space-y-4 custom-scrollbar">
              {filteredGroups.length === 0 ? (
                <div className="p-8 text-center text-xs text-on-surface-variant font-mono flex flex-col items-center gap-2">
                  <Cpu size={28} className="opacity-30" />
                  <span>No matching models found for &ldquo;{search}&rdquo;</span>
                  <button
                    type="button"
                    onClick={() => setSearch("")}
                    className="text-[11px] text-primary-container hover:underline mt-1 cursor-pointer"
                  >
                    Clear search filter
                  </button>
                </div>
              ) : (
                filteredGroups.map((group) => (
                  <div key={group.groupName} className="space-y-2">
                    <div className="px-2 py-1 text-[11px] font-bold uppercase tracking-wider text-on-surface flex items-center justify-between border-b border-white/5">
                      <span className="flex items-center gap-2">
                        <span>{group.groupName}</span>
                      </span>
                      <span className={`text-[9px] px-1.5 py-0.5 rounded font-mono ${getProviderBadgeColor(group.providerId)}`}>
                        {group.providerId}
                      </span>
                    </div>

                    {Array.from(group.seriesMap.entries()).map(([seriesName, sModels]: [string, ModelEntry[]]) => (
                      <div key={seriesName} className="space-y-1">
                        <div className="text-[10px] font-mono text-on-surface-variant/70 uppercase tracking-wide px-2 pt-1 font-semibold">
                          — {seriesName}
                        </div>

                        <div className="grid grid-cols-1 gap-1">
                          {sModels.map((m: ModelEntry) => {
                            const isSelected =
                              !isAuto &&
                              m.model.toLowerCase() === activeModel.toLowerCase() &&
                              (m.provider.toLowerCase() === activeProvider.toLowerCase() || !activeProvider);

                            return (
                              <button
                                key={`${m.provider}:${m.model}`}
                                type="button"
                                onClick={() => {
                                  onSelect(m.provider, m.model);
                                  setIsOpen(false);
                                }}
                                className={`w-full flex items-center justify-between gap-3 p-2.5 px-3.5 rounded-xl text-left transition-all cursor-pointer ${
                                  isSelected
                                    ? "bg-primary-container/20 border border-primary-container/50 text-on-surface font-medium shadow-sm"
                                    : "bg-surface-container/30 hover:bg-white/[0.08] text-on-surface-variant hover:text-on-surface border border-white/5 hover:border-white/15"
                                }`}
                              >
                                <div className="min-w-0 flex-1">
                                  <div className="flex items-center gap-2 min-w-0 flex-wrap">
                                    <span className={`text-xs font-semibold ${isSelected ? "text-primary-container font-bold" : "text-on-surface"}`}>
                                      {m.label}
                                    </span>
                                    {m.badge && (
                                      <span className="text-[9px] px-1.5 py-0.2 rounded font-mono bg-white/10 text-white/90 shrink-0 font-medium border border-white/10">
                                        {m.badge}
                                      </span>
                                    )}
                                  </div>
                                  {m.description && (
                                    <p className="text-[11px] text-on-surface-variant/80 mt-0.5 leading-relaxed">
                                      {m.description}
                                    </p>
                                  )}
                                </div>

                                <div className="flex items-center gap-2 shrink-0 ml-2">
                                  <span className={`text-[9px] px-2 py-0.5 rounded font-mono font-medium ${getProviderBadgeColor(m.provider)}`}>
                                    {m.provider}
                                  </span>
                                  {isSelected && <Check size={16} className="text-primary-container shrink-0" />}
                                </div>
                              </button>
                            );
                          })}
                        </div>
                      </div>
                    ))}
                  </div>
                ))
              )}
            </div>

            {/* Bottom Modal Action Bar */}
            <div className="p-3 px-5 border-t border-white/10 bg-surface-container-lowest/90 flex items-center justify-between gap-3 shrink-0">
              <div className="flex items-center gap-2 text-[11px] text-on-surface-variant font-mono">
                <span>Need a custom endpoint or self-hosted LLM?</span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setIsOpen(false);
                    onOpenCustomModal();
                  }}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-mono bg-surface-container hover:bg-surface-container-high text-primary-container border border-primary-container/30 transition-all cursor-pointer shadow-xs hover:border-primary-container/50"
                >
                  <Plus size={12} />
                  <span>Custom Model...</span>
                </button>
                <button
                  type="button"
                  onClick={() => setIsOpen(false)}
                  className="px-3 py-1.5 rounded-lg text-[11px] font-mono bg-white/5 hover:bg-white/10 text-on-surface border border-white/10 transition-all cursor-pointer"
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export const AgentRoster: React.FC = () => {
  const currentWorkspace = useWorkspaceStore((state) => state.currentWorkspace);
  const workspacePath = currentWorkspace?.path || ".";
  const {
    teamConfig,
    updateTeamConfig,
    agentMetrics,
    tasks,
    jobStatus,
    isVerifying,
    customRoles,
    fetchCustomRoles,
    addCustomRole,
    deleteCustomRole,
    smartRouterEnabled,
    taskDifficultyMap,
    toggleSmartRouter,
  } = useTeamStore();

  const [showSmartRouterModal, setShowSmartRouterModal] = useState(false);
  const [showAddModal, setShowAddModal] = useState(false);
  const [customModalRole, setCustomModalRole] = useState<RoleMetadata | null>(null);
  const [customModelId, setCustomModelId] = useState("");
  const [customProvider, setCustomProvider] = useState("openai");
  const [userCustomModels, setUserCustomModels] = useState<ModelEntry[]>([]);

  // Add Custom Agent Form State
  const [newRoleName, setNewRoleName] = useState("");
  const [newRoleHandle, setNewRoleHandle] = useState("");
  const [newRoleDesc, setNewRoleDesc] = useState("");
  const [newRoleIcon, setNewRoleIcon] = useState("bot");
  const [newRoleColor, setNewRoleColor] = useState("#6366f1");
  const [newRoleTools, setNewRoleTools] = useState<string[]>([
    "read_file",
    "search_code",
    "list_directory",
  ]);
  const [newRoleProvider, setNewRoleProvider] = useState("anthropic");
  const [newRoleModel, setNewRoleModel] = useState("claude-3-5-sonnet-latest");
  const [addError, setAddError] = useState<string | null>(null);
  const [isSubmittingRole, setIsSubmittingRole] = useState(false);

  // Fetch custom roles for active workspace
  useEffect(() => {
    fetchCustomRoles(workspacePath);
  }, [workspacePath, fetchCustomRoles]);

  const handleCreateCustomRole = async (e: React.FormEvent) => {
    e.preventDefault();
    setAddError(null);
    if (!newRoleName.trim()) {
      setAddError("Agent Name is required.");
      return;
    }
    const cleanHandle = newRoleHandle.trim().replace(/^@/, "").toLowerCase();
    if (!cleanHandle) {
      setAddError("Agent Handle is required.");
      return;
    }
    const BUILTIN_HANDLES = new Set(["architect", "coder", "reviewer", "tester", "devops", "operator", "system"]);
    if (BUILTIN_HANDLES.has(cleanHandle)) {
      setAddError(`Handle '@${cleanHandle}' is reserved for built-in roles.`);
      return;
    }
    if (customRoles.some((r) => r.handle.toLowerCase() === cleanHandle)) {
      setAddError(`Handle '@${cleanHandle}' is already used by another custom agent.`);
      return;
    }
    if (newRoleTools.length === 0) {
      setAddError("Please select at least one safe tool for this agent.");
      return;
    }

    try {
      setIsSubmittingRole(true);
      await addCustomRole({
        workspace: workspacePath,
        name: newRoleName.trim(),
        handle: cleanHandle,
        description: newRoleDesc.trim(),
        color: newRoleColor,
        icon: newRoleIcon,
        allowed_tools: newRoleTools,
        provider: newRoleProvider,
        model: newRoleModel,
      });
      // Reset form
      setNewRoleName("");
      setNewRoleHandle("");
      setNewRoleDesc("");
      setNewRoleIcon("bot");
      setNewRoleColor("#6366f1");
      setNewRoleTools(["read_file", "search_code", "list_directory"]);
      setShowAddModal(false);
    } catch (err: any) {
      setAddError(err?.message || "Failed to create custom role");
    } finally {
      setIsSubmittingRole(false);
    }
  };

  // Load user custom models from localStorage
  useEffect(() => {
    try {
      const raw = localStorage.getItem(CUSTOM_MODELS_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) setUserCustomModels(parsed);
      }
    } catch {
      // ignore
    }
  }, []);

  const handleSaveCustomModel = (e: React.FormEvent) => {
    e.preventDefault();
    if (!customModalRole || !customModelId.trim()) return;

    const trimmedModel = customModelId.trim();
    const newEntry: ModelEntry = {
      label: `${trimmedModel} (${customProvider})`,
      model: trimmedModel,
      provider: customProvider,
      series: "Custom User Models",
      badge: "Custom",
      description: `Custom model on ${customProvider}`,
    };

    const updated = [newEntry, ...userCustomModels.filter((m) => m.model !== trimmedModel || m.provider !== customProvider)];
    setUserCustomModels(updated);
    try {
      localStorage.setItem(CUSTOM_MODELS_KEY, JSON.stringify(updated));
    } catch {
      // ignore
    }

    // Apply to selected role
    updateTeamConfig({
      [MODEL_KEYS[customModalRole.modelKey]]: trimmedModel,
      [PROVIDER_KEYS[customModalRole.providerKey]]: customProvider,
      auto_model_selection: false,
    });

    setCustomModalRole(null);
    setCustomModelId("");
  };

  const allAuto = ROLES.every(
    (r) => teamConfig[MODEL_KEYS[r.modelKey]] === "auto" || teamConfig.auto_model_selection
  );

  const handleToggleAllAuto = () => {
    if (allAuto) {
      updateTeamConfig({
        architect_model: "gpt-4o",
        architect_provider: "openai",
        coder_model: "claude-3-5-sonnet-latest",
        coder_provider: "anthropic",
        reviewer_model: "gpt-4o",
        reviewer_provider: "openai",
        tester_model: "llama-3.3-70b-versatile",
        tester_provider: "groq",
        devops_model: "llama-3.1-8b-instant",
        devops_provider: "groq",
        auto_model_selection: false,
      });
    } else {
      updateTeamConfig({
        architect_model: "auto",
        architect_provider: "auto",
        coder_model: "auto",
        coder_provider: "auto",
        reviewer_model: "auto",
        reviewer_provider: "auto",
        tester_model: "auto",
        tester_provider: "auto",
        devops_model: "auto",
        devops_provider: "auto",
        auto_model_selection: true,
      });
    }
  };

  const getRoleStatus = (role: TeamRole) => {
    const roleTasks = tasks.filter((t) => t.assigned_agent === role);
    if (roleTasks.some((t) => t.status === "running")) return "running";
    if (roleTasks.some((t) => t.status === "failed")) return "failed";
    if (roleTasks.length > 0 && roleTasks.every((t) => t.status === "completed")) return "completed";
    if (roleTasks.some((t) => t.status === "waiting" || t.status === "pending" || t.status === "queued")) {
      return "waiting";
    }
    return "idle";
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "running":
        return (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-primary-container/20 text-primary-container border border-primary-container/40 flex items-center gap-1 shrink-0 uppercase tracking-wider">
            <span className="w-1.5 h-1.5 rounded-full bg-primary-container animate-pulse shrink-0" />
            RUNNING
          </span>
        );
      case "completed":
        return (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 shrink-0 uppercase tracking-wider">
            DONE
          </span>
        );
      case "failed":
        return (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-error/20 text-error border border-error/30 shrink-0 uppercase tracking-wider">
            FAILED
          </span>
        );
      case "waiting":
        return (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30 shrink-0 uppercase tracking-wider">
            WAITING
          </span>
        );
      default:
        return (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-white/5 text-on-surface-variant/70 border border-white/10 shrink-0 uppercase tracking-wider flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-white/30 shrink-0" />
            IDLE
          </span>
        );
    }
  };

  return (
    <div className="flex flex-col gap-3 h-full min-w-0 select-none">
      {/* Roster Header: Clean 2-row layout preventing any clipping on narrow sidebars */}
      <div className="flex flex-col gap-2 px-0.5 shrink-0 min-w-0 border-b border-white/10 pb-2.5">
        {/* Row 1: Title, Count Badge, and Action Buttons */}
        <div className="flex items-center justify-between gap-2 min-w-0">
          <div className="flex items-center gap-1.5 min-w-0">
            <div className="w-5 h-5 rounded-md bg-primary-container/20 border border-primary-container/30 flex items-center justify-center shrink-0">
              <Zap size={12} className="text-primary-container" />
            </div>
            <h2 className="text-xs font-bold uppercase tracking-wider text-white shrink-0">
              Agent Roster
            </h2>
            <span className="px-1.5 py-0.5 rounded-full text-[10px] font-semibold bg-white/10 text-white/80 shrink-0">
              {ROLES.length + customRoles.length}
            </span>
            {(isVerifying || jobStatus === "verifying") && (
              <span
                data-testid="verification-badge"
                className="px-1.5 py-0.5 rounded-full text-[9px] font-bold bg-purple-500/20 text-purple-300 border border-purple-500/40 animate-pulse flex items-center gap-1 shrink-0 whitespace-nowrap"
              >
                <span className="w-1.5 h-1.5 rounded-full bg-purple-400 animate-ping shrink-0" />
                Verification in progress...
              </span>
            )}
          </div>

          <div className="flex items-center gap-1 shrink-0">
            {/* Smart Router Settings Button */}
            <button
              onClick={() => setShowSmartRouterModal(true)}
              data-testid="smart-router-settings-btn"
              title="Configure Smart Router Model Tiers"
              className="flex items-center gap-1 px-2 py-1 rounded-md text-[10.5px] font-medium bg-white/[0.06] hover:bg-white/[0.12] text-white/80 hover:text-white border border-white/10 transition-colors cursor-pointer shrink-0"
            >
              <Wrench size={11} className="text-white/60" />
              <span>Tiers</span>
            </button>

            {/* Add Custom Agent Role */}
            <button
              onClick={() => setShowAddModal(true)}
              className="flex items-center gap-1 px-2 py-1 rounded-md text-[10.5px] font-medium bg-white/[0.06] hover:bg-white/[0.12] text-white/80 hover:text-white border border-white/10 transition-colors cursor-pointer shrink-0"
              title="Add Custom Agent Role"
            >
              <Plus size={11} className="text-white/60" />
              <span>Add Agent</span>
            </button>
          </div>
        </div>

        {/* Row 2: Control Toggles (Smart Router & Auto Mode) */}
        <div className="grid grid-cols-2 gap-1.5 min-w-0">
          {/* Smart Model Router Toggle */}
          <button
            onClick={() => toggleSmartRouter()}
            data-testid="smart-model-router-toggle"
            title="Automatically routes tasks to optimal models"
            className={`flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-lg text-[10.5px] font-medium border transition-all cursor-pointer truncate ${
              smartRouterEnabled
                ? "bg-primary-container/20 text-primary-container border-primary-container/40 font-semibold shadow-xs"
                : "bg-surface-container hover:bg-surface-container-high text-white/70 hover:text-white border-white/10"
            }`}
          >
            <Cpu size={12} className={smartRouterEnabled ? "text-primary-container animate-pulse shrink-0" : "text-white/50 shrink-0"} />
            <span className="truncate">Smart Router: {smartRouterEnabled ? "ON" : "OFF"}</span>
          </button>

          {/* Quick Toggle for Auto Model Selection */}
          <button
            onClick={handleToggleAllAuto}
            data-testid="toggle-all-auto-models"
            className={`flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-lg text-[10.5px] font-medium border transition-all cursor-pointer truncate ${
              allAuto
                ? "bg-primary-container/20 text-primary-container border-primary-container/40 font-semibold shadow-xs"
                : "bg-surface-container hover:bg-surface-container-high text-white/70 hover:text-white border-white/10"
            }`}
            title="Toggle dynamic difficulty-based model selection across all agents"
          >
            <Sparkles size={12} className={allAuto ? "text-primary-container animate-spin shrink-0" : "text-white/50 shrink-0"} />
            <span className="truncate">Auto: {allAuto ? "ON" : "OFF"}</span>
          </button>
        </div>
      </div>

      {/* Roster Cards Grid */}
      <div className="flex-1 flex flex-col gap-2.5 overflow-y-auto pr-1 min-w-0 custom-scrollbar">
        {ROLES.map((r) => {
          const Icon = r.icon;
          const status = getRoleStatus(r.role);
          const currentRunningTask = tasks.find(
            (t) => t.assigned_agent === r.role && t.status === "running"
          );
          const metrics = agentMetrics[r.role] || {
            total_tokens: 0,
            input_tokens: 0,
            output_tokens: 0,
            total_cost: 0,
            message_count: 0,
          };

          const activeModel = teamConfig[MODEL_KEYS[r.modelKey]] || "gpt-4o";
          const activeProvider = teamConfig[PROVIDER_KEYS[r.providerKey]] || "openai";
          const isAutoRole = activeModel === "auto" || teamConfig.auto_model_selection;
          const pricing = getPricingForModel(activeModel);
          const inTokens = metrics.input_tokens || 0;
          const outTokens = metrics.output_tokens || 0;
          const inCost = (inTokens / 1_000_000) * pricing.inputPerMillion;
          const outCost = (outTokens / 1_000_000) * pricing.outputPerMillion;
          const calculatedCost = inCost + outCost;
          const totalCost = metrics.total_cost > 0 ? metrics.total_cost : calculatedCost;

          const roleTasks = tasks.filter((t) => t.assigned_agent === r.role);
          const roleDiffInfo = currentRunningTask
            ? taskDifficultyMap[currentRunningTask.id]
            : roleTasks.map((t) => taskDifficultyMap[t.id]).filter(Boolean).pop();

          const roleDefaultLabels: Record<string, string> = {
            architect: "GLM 5.2 (HARD)",
            coder: "Claude Sonnet 5 (MEDIUM)",
            reviewer: "GLM 5.2 (HARD)",
            tester: "Groq (EASY)",
            devops: "Groq (EASY)",
          };

          const smartTierBadgeText = roleDiffInfo
            ? `${roleDiffInfo.assigned_model} (${roleDiffInfo.tier || roleDiffInfo.difficulty})`
            : (roleDefaultLabels[r.role.toLowerCase()] || "Auto (MEDIUM)");

          return (
            <div
              key={r.role}
              data-testid={`agent-card-${r.role}`}
              className={`rounded-xl p-3 border border-white/10 border-l-[3px] ${r.borderLeft} bg-gradient-to-b from-[#181922] to-[#12131a] hover:border-white/20 transition-all flex flex-col gap-2.5 shadow-sm relative min-w-0`}
            >
              {/* Card Header */}
              <div className="flex items-start justify-between gap-2 min-w-0">
                <div className="flex items-center gap-2.5 min-w-0 flex-1">
                  <div className={`p-2 rounded-lg ${r.bgGlow} ${r.color} ring-1 ${r.borderColor} shrink-0`}>
                    <Icon size={16} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <h3 className="text-xs font-bold text-white truncate">{r.displayName}</h3>
                      <span className="text-[10.5px] text-white/40 font-mono lowercase shrink-0">
                        @{r.role}
                      </span>
                    </div>
                    <p className="text-[10.5px] text-white/60 truncate mt-0.5">
                      {r.description}
                    </p>
                  </div>
                </div>
                <div className="shrink-0">{getStatusBadge(status)}</div>
              </div>

              {/* Current Active Task (if running) */}
              {currentRunningTask && (
                <div className="bg-primary-container/10 border border-primary-container/20 rounded-lg px-2.5 py-1.5 flex items-center gap-2 min-w-0">
                  <Activity size={12} className="text-primary-container animate-spin shrink-0" />
                  <span className="text-[11px] font-medium text-primary-container truncate flex-1">
                    {currentRunningTask.title}
                  </span>
                </div>
              )}

              {/* Model Selector Dropdown with Full Model Freedom & Auto Mode */}
              <div className="flex flex-col gap-1 min-w-0">
                <div className="flex items-center justify-between gap-2 min-w-0">
                  <label className="text-[10.5px] font-medium text-white/70 shrink-0 flex items-center gap-1.5">
                    <Cpu size={11} className="text-primary-container" />
                    <span>Model:</span>
                  </label>

                  {smartRouterEnabled ? (
                    <span
                      data-testid={`smart-router-tier-${r.role}`}
                      className="text-[9px] font-mono px-1.5 py-0.5 rounded-md bg-primary-container/20 text-primary-container border border-primary-container/30 flex items-center gap-1 shrink-0 font-bold"
                      title="Smart Router Assigned Model & Tier"
                    >
                      <Cpu size={9} />
                      {smartTierBadgeText}
                    </span>
                  ) : isAutoRole ? (
                    <span className="text-[9px] font-mono px-1.5 py-0.2 rounded-full bg-primary-container/15 text-primary-container border border-primary-container/30 flex items-center gap-1 shrink-0">
                      <Sparkles size={8} />
                      Route by Difficulty
                    </span>
                  ) : null}
                </div>

                <AgentModelDropdown
                  roleMeta={r}
                  activeModel={activeModel}
                  activeProvider={activeProvider}
                  isAuto={Boolean(isAutoRole)}
                  disabled={jobStatus === "running" || jobStatus === "verifying"}
                  userCustomModels={userCustomModels}
                  onSelect={(provider, model) => {
                    updateTeamConfig({
                      [MODEL_KEYS[r.modelKey]]: model,
                      [PROVIDER_KEYS[r.providerKey]]: provider,
                      auto_model_selection: false,
                    });
                  }}
                  onOpenCustomModal={() => setCustomModalRole(r)}
                  onSelectAuto={() => {
                    updateTeamConfig({
                      [MODEL_KEYS[r.modelKey]]: "auto",
                      [PROVIDER_KEYS[r.providerKey]]: "auto",
                    });
                  }}
                />
              </div>

              {/* Live Cost Breakdown per Role */}
              <div
                data-testid={`cost-breakdown-${r.role}`}
                className="mt-0.5 p-2 rounded-lg bg-black/35 border border-white/5 flex flex-col gap-1 text-[10.5px] font-sans text-white/80"
              >
                <div className="flex items-center justify-between text-white/70">
                  <span className="flex items-center gap-1.5">
                    <Coins size={11} className="text-amber-400/90 shrink-0" />
                    Input tokens: {inTokens.toLocaleString()} (${inCost.toFixed(2)})
                  </span>
                </div>
                <div className="flex items-center justify-between text-white/70">
                  <span className="flex items-center gap-1.5">
                    <span className="w-2.5" />
                    Output tokens: {outTokens.toLocaleString()} (${outCost.toFixed(2)})
                  </span>
                </div>
                <div className="flex items-center justify-between pt-1.5 border-t border-white/5 font-semibold text-xs">
                  <span className="text-emerald-400">Total: ${totalCost.toFixed(2)}</span>
                  {metrics.total_tokens > 0 ? (
                    <div className="flex items-center gap-1.5 text-[9.5px] font-normal text-white/60">
                      <span className="px-1.5 py-0.2 rounded bg-white/10 font-mono text-white/80 flex items-center gap-1">
                        <span>{metrics.total_tokens.toLocaleString()}</span>
                        <span className="text-white/50 text-[8.5px]">tok</span>
                      </span>
                      <span className="text-emerald-400 font-mono font-medium">${metrics.total_cost.toFixed(4)}</span>
                    </div>
                  ) : (
                    <span className="text-[9px] text-white/30 font-mono">0 tok</span>
                  )}
                </div>
              </div>
            </div>
          );
        })}

        {/* Custom Agent Roles (Phase B7) */}
        {customRoles.map((cr) => {
          const Icon = getCustomRoleIcon(cr.icon);
          const colorCfg = getColorConfig(cr.color);
          const customTasks = tasks.filter((t) => {
            const a = (t.assigned_agent || "").toLowerCase();
            const h = cr.handle.toLowerCase();
            return a === h || a === `@${h}`;
          });
          let status = "idle";
          if (customTasks.some((t) => t.status === "running")) status = "running";
          else if (customTasks.some((t) => t.status === "failed")) status = "failed";
          else if (customTasks.length > 0 && customTasks.every((t) => t.status === "completed")) status = "completed";
          else if (customTasks.some((t) => t.status === "waiting" || t.status === "pending" || t.status === "queued")) status = "waiting";

          const currentRunningTask = customTasks.find((t) => t.status === "running");
          const metrics = agentMetrics[cr.handle] || {
            total_tokens: 0,
            input_tokens: 0,
            output_tokens: 0,
            total_cost: 0,
            message_count: 0,
          };
          const pricing = getPricingForModel(cr.model || "claude-3-5-sonnet-latest");
          const inTokens = metrics.input_tokens || 0;
          const outTokens = metrics.output_tokens || 0;
          const inCost = (inTokens / 1_000_000) * pricing.inputPerMillion;
          const outCost = (outTokens / 1_000_000) * pricing.outputPerMillion;
          const calculatedCost = inCost + outCost;
          const totalCost = metrics.total_cost > 0 ? metrics.total_cost : calculatedCost;

          return (
            <div
              key={cr.id || cr.handle}
              data-testid={`agent-card-${cr.handle}`}
              className={`rounded-xl p-3 border border-white/10 border-l-[3px] ${colorCfg.borderLeft} bg-gradient-to-b from-[#181922] to-[#12131a] hover:border-white/20 transition-all flex flex-col gap-2.5 shadow-sm relative min-w-0`}
            >
              {/* Card Header */}
              <div className="flex items-start justify-between gap-2 min-w-0">
                <div className="flex items-center gap-2.5 min-w-0 flex-1">
                  <div className={`p-2 rounded-lg ${colorCfg.bgGlow} ${colorCfg.color} ring-1 ${colorCfg.borderColor} shrink-0`}>
                    <Icon size={16} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5 min-w-0 flex-wrap">
                      <h3 className="text-xs font-bold text-on-surface truncate">{cr.name}</h3>
                      <span className="text-[10px] text-on-surface-variant font-mono lowercase shrink-0">
                        @{cr.handle}
                      </span>
                      <span className="text-[9px] font-mono font-bold px-1.5 py-0.2 rounded bg-primary-container/20 text-primary-container border border-primary-container/30 shrink-0">
                        CUSTOM
                      </span>
                    </div>
                    <p className="text-[10px] text-on-surface-variant/80 truncate">
                      {cr.description || "Custom provisioned agent role"}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                  {getStatusBadge(status)}
                  <button
                    data-testid={`delete-role-${cr.handle}`}
                    type="button"
                    onClick={async () => {
                      try {
                        await deleteCustomRole(cr.id, workspacePath);
                      } catch (e) {
                        console.error(e);
                      }
                    }}
                    className="p-1 rounded text-on-surface-variant hover:text-rose-400 hover:bg-rose-500/10 transition-colors cursor-pointer"
                    title={`Delete @${cr.handle}`}
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              </div>

              {/* Active Running Task */}
              {currentRunningTask && (
                <div className="bg-primary-container/10 border border-primary-container/20 rounded-lg px-2.5 py-1.5 flex items-center gap-2 min-w-0">
                  <Activity size={12} className="text-primary-container animate-spin shrink-0" />
                  <span className="text-[11px] font-medium text-primary-container truncate flex-1">
                    {currentRunningTask.title}
                  </span>
                </div>
              )}

              {/* Model & Allowed Tools */}
              <div className="flex flex-col gap-1.5 min-w-0 text-[10px]">
                <div className="flex items-center justify-between gap-1">
                  <span className="text-on-surface-variant font-mono flex items-center gap-1">
                    <Cpu size={10} className="text-primary-container" />
                    <span>{cr.model || "claude-3-5-sonnet-latest"}</span>
                  </span>
                  <span className={`text-[9px] px-1.5 py-0.2 rounded font-mono ${getProviderBadgeColor(cr.provider || "anthropic")}`}>
                    {cr.provider || "anthropic"}
                  </span>
                </div>

                <div className="flex flex-wrap gap-1 pt-0.5">
                  {(cr.allowed_tools || []).map((tool) => (
                    <span
                      key={tool}
                      className="px-1.5 py-0.5 rounded text-[9px] font-mono bg-white/5 text-on-surface-variant border border-white/5 truncate max-w-[150px]"
                    >
                      {tool}
                    </span>
                  ))}
                </div>
              </div>

              {/* Metrics Breakdown */}
              <div
                data-testid={`cost-breakdown-${cr.handle}`}
                className="mt-0.5 p-2 rounded-lg bg-black/35 border border-white/5 flex flex-col gap-1 text-[10.5px] font-sans text-white/80"
              >
                <div className="flex items-center justify-between text-white/70">
                  <span className="flex items-center gap-1.5">
                    <Coins size={11} className="text-amber-400/90 shrink-0" />
                    Input tokens: {inTokens.toLocaleString()} (${inCost.toFixed(2)})
                  </span>
                </div>
                <div className="flex items-center justify-between text-white/70">
                  <span className="flex items-center gap-1.5">
                    <span className="w-2.5" />
                    Output tokens: {outTokens.toLocaleString()} (${outCost.toFixed(2)})
                  </span>
                </div>
                <div className="flex items-center justify-between pt-1.5 border-t border-white/5 font-semibold text-xs">
                  <span className="text-emerald-400">Total: ${totalCost.toFixed(2)}</span>
                  {metrics.total_tokens > 0 ? (
                    <div className="flex items-center gap-1.5 text-[9.5px] font-normal text-white/60">
                      <span className="px-1.5 py-0.2 rounded bg-white/10 font-mono text-white/80 flex items-center gap-1">
                        <span>{metrics.total_tokens.toLocaleString()}</span>
                        <span className="text-white/50 text-[8.5px]">tok</span>
                      </span>
                      <span className="text-emerald-400 font-mono font-medium">${metrics.total_cost.toFixed(4)}</span>
                    </div>
                  ) : (
                    <span className="text-[9px] text-white/30 font-mono">0 tok</span>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Custom Model Freedom Modal */}
      {customModalRole && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-surface-container border border-white/15 rounded-xl p-5 max-w-md w-full flex flex-col gap-4 shadow-2xl animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between border-b border-white/10 pb-2">
              <div className="flex items-center gap-2 text-on-surface font-bold text-xs">
                <Cpu size={15} className="text-primary-container" />
                <span>Configure Custom Model for {customModalRole.displayName}</span>
              </div>
              <button
                onClick={() => setCustomModalRole(null)}
                className="text-on-surface-variant hover:text-on-surface text-sm cursor-pointer"
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleSaveCustomModel} className="flex flex-col gap-3 text-xs">
              <div className="flex flex-col gap-1">
                <label className="text-[11px] text-on-surface-variant font-mono">Provider:</label>
                <select
                  value={customProvider}
                  onChange={(e) => setCustomProvider(e.target.value)}
                  style={{ backgroundColor: "#16171b", color: "#e5e1e4" }}
                  className="bg-surface-container-lowest border border-white/10 rounded-lg p-2 text-xs text-on-surface font-mono focus:outline-none focus:border-primary-container"
                >
                  <option value="openai">OpenAI</option>
                  <option value="anthropic">Anthropic</option>
                  <option value="gemini">Google Gemini</option>
                  <option value="groq">Groq</option>
                  <option value="deepseek">DeepSeek</option>
                  <option value="openrouter">OpenRouter</option>
                  <option value="mistral">Mistral AI</option>
                  <option value="xai">xAI (Grok)</option>
                  <option value="ollama">Ollama (Local)</option>
                  <option value="nvidia-nim">NVIDIA NIM</option>
                  <option value="cohere">Cohere</option>
                  <option value="custom">Custom Endpoint</option>
                </select>
              </div>

              <div className="flex flex-col gap-1">
                <label className="text-[11px] text-on-surface-variant font-mono">Model ID / Name:</label>
                <input
                  type="text"
                  value={customModelId}
                  onChange={(e) => setCustomModelId(e.target.value)}
                  placeholder="e.g. ft:gpt-4o:org:123 or meta-llama/llama-3.2-3b"
                  required
                  className="bg-surface-container-lowest border border-white/10 rounded-lg p-2 text-xs text-on-surface font-mono focus:outline-none focus:border-primary-container"
                />
                <span className="text-[10px] text-on-surface-variant/70">
                  Enter any valid model identifier for the chosen provider.
                </span>
              </div>

              <div className="flex justify-end gap-2 pt-2 border-t border-white/10">
                <button
                  type="button"
                  onClick={() => setCustomModalRole(null)}
                  className="px-3 py-1.5 rounded-lg text-xs bg-surface-container-high text-on-surface-variant hover:text-on-surface border border-white/10 cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-3.5 py-1.5 rounded-lg text-xs bg-primary-container text-on-primary-container font-semibold hover:opacity-90 cursor-pointer shadow-sm"
                >
                  Apply Model
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Add Custom Agent Modal (Phase B7: Real Provisioning) */}
      {showAddModal && (
        <div
          className="fixed inset-0 bg-black/80 backdrop-blur-md z-50 flex items-center justify-center p-3 sm:p-6 animate-in fade-in duration-150"
          onClick={(e) => {
            if (e.target === e.currentTarget) setShowAddModal(false);
          }}
        >
          <div
            className="bg-[#111216] border border-white/15 rounded-2xl shadow-[0_32px_96px_rgba(0,0,0,0.95)] max-w-lg w-full flex flex-col max-h-[90vh] overflow-hidden animate-in zoom-in-95 duration-150"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div className="p-4 px-5 border-b border-white/10 bg-surface-container-lowest flex items-center justify-between gap-3 shrink-0">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-xl bg-primary-container/20 border border-primary-container/30 flex items-center justify-center text-primary-container">
                  <Plus size={16} />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-on-surface">Provision Custom Agent</h3>
                  <p className="text-[11px] text-on-surface-variant">
                    Workspace-scoped autonomous role with sandboxed tool access
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setShowAddModal(false)}
                className="text-on-surface-variant hover:text-on-surface p-1 rounded-lg hover:bg-white/10 transition-colors cursor-pointer"
              >
                <X size={16} />
              </button>
            </div>

            {/* Scrollable Form Body */}
            <form onSubmit={handleCreateCustomRole} className="flex-1 overflow-y-auto p-5 space-y-4 custom-scrollbar text-xs">
              {/* Safety Alert Banner */}
              <div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 text-[11px] flex items-start gap-2.5">
                <ShieldCheck size={16} className="text-emerald-400 shrink-0 mt-0.5" />
                <div className="space-y-0.5">
                  <span className="font-bold">Strict Safety Bounds Enforced</span>
                  <p className="text-emerald-300/80 leading-relaxed">
                    Custom agents only have access to allowlisted, safe workspace tools. Shell execution is strictly bounded to developer CLI tools (<code className="text-emerald-200">git, npm, npx, pytest, python -m, node</code>). Unrestricted terminal, browser, and computer-use tools are rejected.
                  </p>
                </div>
              </div>

              {addError && (
                <div className="p-2.5 rounded-lg bg-rose-500/15 border border-rose-500/30 text-rose-300 text-xs flex items-center gap-2">
                  <AlertTriangle size={14} className="shrink-0" />
                  <span>{addError}</span>
                </div>
              )}

              {/* Name & Handle Inputs */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="flex flex-col gap-1">
                  <label className="text-[11px] font-semibold text-on-surface">Agent Name *</label>
                  <input
                    type="text"
                    data-testid="custom-role-name-input"
                    value={newRoleName}
                    onChange={(e) => {
                      setNewRoleName(e.target.value);
                      if (!newRoleHandle) {
                        setNewRoleHandle(e.target.value.toLowerCase().replace(/[^a-z0-9]/g, ""));
                      }
                    }}
                    placeholder="e.g. Security Auditor"
                    required
                    className="bg-surface-container-lowest border border-white/10 rounded-lg p-2 text-xs text-on-surface focus:outline-none focus:border-primary-container font-mono"
                  />
                </div>

                <div className="flex flex-col gap-1">
                  <label className="text-[11px] font-semibold text-on-surface">Handle *</label>
                  <div className="relative flex items-center">
                    <span className="absolute left-2.5 text-on-surface-variant font-mono text-xs">@</span>
                    <input
                      type="text"
                      data-testid="custom-role-handle-input"
                      value={newRoleHandle}
                      onChange={(e) => setNewRoleHandle(e.target.value.replace(/^@/, "").toLowerCase())}
                      placeholder="auditor"
                      required
                      className="w-full bg-surface-container-lowest border border-white/10 rounded-lg p-2 pl-6 text-xs text-on-surface focus:outline-none focus:border-primary-container font-mono"
                    />
                  </div>
                </div>
              </div>

              {/* Description Input */}
              <div className="flex flex-col gap-1">
                <label className="text-[11px] font-semibold text-on-surface">Description</label>
                <input
                  type="text"
                  data-testid="custom-role-desc-input"
                  value={newRoleDesc}
                  onChange={(e) => setNewRoleDesc(e.target.value)}
                  placeholder="e.g. Scans source code for vulnerabilities, secrets, and CVEs"
                  className="bg-surface-container-lowest border border-white/10 rounded-lg p-2 text-xs text-on-surface focus:outline-none focus:border-primary-container"
                />
              </div>

              {/* Icon Picker (Refinement R2: 16 icons) */}
              <div className="flex flex-col gap-1.5">
                <label className="text-[11px] font-semibold text-on-surface flex items-center justify-between">
                  <span>Icon</span>
                  <span className="text-[10px] font-mono text-on-surface-variant font-normal">Selected: {newRoleIcon}</span>
                </label>
                <div className="grid grid-cols-8 gap-1.5 p-2 rounded-xl bg-surface-container-lowest border border-white/5">
                  {AVAILABLE_ICONS.map((item) => {
                    const IconComp = item.icon;
                    const isSelected = newRoleIcon === item.id;
                    return (
                      <button
                        key={item.id}
                        type="button"
                        data-testid={`icon-pick-${item.id}`}
                        onClick={() => setNewRoleIcon(item.id)}
                        className={`p-2 rounded-lg flex items-center justify-center transition-all cursor-pointer ${
                          isSelected
                            ? "bg-primary-container/20 text-primary-container ring-2 ring-primary-container"
                            : "text-on-surface-variant hover:text-on-surface hover:bg-white/5"
                        }`}
                        title={item.label}
                      >
                        <IconComp size={16} />
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Color Accent Picker */}
              <div className="flex flex-col gap-1.5">
                <label className="text-[11px] font-semibold text-on-surface">Color Accent</label>
                <div className="flex items-center gap-2 p-2 rounded-xl bg-surface-container-lowest border border-white/5 overflow-x-auto custom-scrollbar">
                  {PRESET_COLORS.map((c) => {
                    const isSelected = newRoleColor === c.hex;
                    return (
                      <button
                        key={c.hex}
                        type="button"
                        data-testid={`color-pick-${c.hex}`}
                        onClick={() => setNewRoleColor(c.hex)}
                        className={`w-6 h-6 rounded-full shrink-0 transition-transform cursor-pointer relative flex items-center justify-center ${
                          isSelected ? "scale-110 ring-2 ring-white ring-offset-2 ring-offset-black" : "hover:scale-105"
                        }`}
                        style={{ backgroundColor: c.hex }}
                        title={c.name}
                      >
                        {isSelected && <Check size={12} className="text-black font-bold" />}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Safe Tools Grouped Checkboxes */}
              <div className="flex flex-col gap-1.5">
                <label className="text-[11px] font-semibold text-on-surface flex items-center justify-between">
                  <span>Allowed Tools</span>
                  <span className="text-[10px] font-mono text-on-surface-variant font-normal">
                    {newRoleTools.length} selected
                  </span>
                </label>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 p-2.5 rounded-xl bg-surface-container-lowest border border-white/5 max-h-48 overflow-y-auto custom-scrollbar">
                  {SAFE_CUSTOM_TOOLS.map((t) => {
                    const checked = newRoleTools.includes(t.id);
                    return (
                      <label
                        key={t.id}
                        className={`flex items-start gap-2 p-2 rounded-lg border text-left cursor-pointer transition-all ${
                          checked
                            ? "bg-primary-container/10 border-primary-container/30 text-on-surface"
                            : "bg-surface-container/40 border-white/5 text-on-surface-variant hover:text-on-surface"
                        }`}
                      >
                        <input
                          type="checkbox"
                          data-testid={`tool-checkbox-${t.id}`}
                          checked={checked}
                          onChange={(e) => {
                            if (e.target.checked) {
                              setNewRoleTools([...newRoleTools, t.id]);
                            } else {
                              setNewRoleTools(newRoleTools.filter((tid) => tid !== t.id));
                            }
                          }}
                          className="mt-0.5 rounded border-white/20 text-primary-container focus:ring-0 cursor-pointer"
                        />
                        <div className="min-w-0 flex-1">
                          <div className="font-mono text-[11px] font-semibold truncate">{t.label}</div>
                          <div className="text-[10px] text-on-surface-variant/70 leading-tight mt-0.5">{t.description}</div>
                        </div>
                      </label>
                    );
                  })}
                </div>
              </div>

              {/* Model & Provider */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="flex flex-col gap-1">
                  <label className="text-[11px] font-semibold text-on-surface">Provider</label>
                  <select
                    value={newRoleProvider}
                    onChange={(e) => {
                      const nextP = e.target.value;
                      setNewRoleProvider(nextP);
                      const defaults: Record<string, string> = {
                        anthropic: "claude-3-5-sonnet-latest",
                        openai: "gpt-4o",
                        groq: "llama-3.3-70b-versatile",
                        gemini: "gemini-2.0-flash",
                        deepseek: "deepseek-chat",
                        mistral: "codestral-latest",
                        xai: "grok-2",
                        ollama: "qwen2.5-coder:7b",
                      };
                      if (defaults[nextP]) {
                        setNewRoleModel(defaults[nextP]);
                      }
                    }}
                    style={{ backgroundColor: "#16171b", color: "#e5e1e4" }}
                    className="bg-surface-container-lowest border border-white/10 rounded-lg p-2 text-xs text-on-surface font-mono focus:outline-none focus:border-primary-container"
                  >
                    <option value="anthropic">Anthropic (Claude)</option>
                    <option value="openai">OpenAI (GPT)</option>
                    <option value="groq">Groq (LPU Speed)</option>
                    <option value="gemini">Google Gemini</option>
                    <option value="deepseek">DeepSeek</option>
                    <option value="mistral">Mistral AI</option>
                    <option value="xai">xAI Grok</option>
                    <option value="ollama">Ollama (Local)</option>
                  </select>
                </div>

                <div className="flex flex-col gap-1">
                  <label className="text-[11px] font-semibold text-on-surface">Model</label>
                  <LiquidGlassModelSelector
                    value={newRoleModel}
                    provider={newRoleProvider}
                    onChange={(m) => setNewRoleModel(m)}
                    testId="custom-role-model-trigger"
                    inputTestId="custom-role-model-input"
                    placeholder="Choose or search model..."
                    compact
                  />
                  <input
                    type="hidden"
                    name="model"
                    value={newRoleModel}
                    required
                  />
                </div>
              </div>

              {/* Bottom Action Buttons */}
              <div className="flex items-center justify-end gap-2 pt-3 border-t border-white/10">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="px-3.5 py-1.5 rounded-lg text-xs font-mono bg-white/5 hover:bg-white/10 text-on-surface border border-white/10 transition-colors cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  data-testid="create-custom-role-btn"
                  disabled={isSubmittingRole}
                  className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-mono bg-primary-container text-on-primary-container font-bold hover:opacity-90 transition-all cursor-pointer shadow-sm disabled:opacity-50"
                >
                  <Plus size={13} />
                  <span>{isSubmittingRole ? "Creating..." : "Create Role"}</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Smart Model Router Settings Modal */}
      <SmartRouterPanel
        isOpen={showSmartRouterModal}
        onClose={() => setShowSmartRouterModal(false)}
      />
    </div>
  );
};
