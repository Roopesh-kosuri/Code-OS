export function isReasoningModel(model: string): boolean {
  return /(^|[-_/:])(r1|o1|o3|reasoner|reasoning|thinking)([-_/:]|$)/i.test(model);
}
