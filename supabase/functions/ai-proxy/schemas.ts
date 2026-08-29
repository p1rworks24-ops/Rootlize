const entity = {
  type: "object",
  properties: {
    name: { type: "string", maxLength: 80 },
    kind: {
      type: "string",
      enum: ["animal", "person", "character", "object", "place", "other"],
    },
    attributes: { type: "array", items: { type: "string", maxLength: 80 }, maxItems: 8 },
    colors: { type: "array", items: { type: "string", maxLength: 40 }, maxItems: 6 },
    states: { type: "array", items: { type: "string", maxLength: 60 }, maxItems: 6 },
    posture: { type: "string", maxLength: 40 },
    observed_color_description: { type: "string", maxLength: 120 },
    visibility: { type: "string", enum: ["visible", "partially_visible", "nested"] },
    identifiability: { type: "string", enum: ["clear", "partial"] },
  },
  required: [
    "name",
    "kind",
    "attributes",
    "colors",
    "states",
    "posture",
    "observed_color_description",
    "visibility",
    "identifiability",
  ],
  additionalProperties: false,
};

const application = {
  type: "object",
  properties: {
    name: { type: "string", maxLength: 80 },
    category: { type: "string", maxLength: 80 },
    kind: {
      type: "string",
      enum: ["os", "application", "website", "service", "game", "other"],
    },
    role: { type: "string", enum: ["primary", "secondary", "incidental"] },
    theme: { type: "string", enum: ["dark", "light", "mixed", "unknown"] },
    visible_content: { type: "string", maxLength: 240 },
  },
  required: ["name", "category", "kind", "role", "theme", "visible_content"],
  additionalProperties: false,
};

export function factSchema(imageIds: number[]) {
  const item = {
    type: "object",
    properties: {
      image_id: { type: "integer", enum: imageIds },
      media_type: {
        type: "string",
        enum: ["photograph", "screenshot", "illustration", "mixed", "other"],
      },
      scene_description: { type: "string", maxLength: 500 },
      environment: { type: "string", maxLength: 240 },
      ui_types: { type: "array", items: { type: "string", maxLength: 80 }, maxItems: 8 },
      entities: { type: "array", items: entity, maxItems: 12 },
      applications: { type: "array", items: application, maxItems: 12 },
      activities: { type: "array", items: { type: "string", maxLength: 120 }, maxItems: 10 },
      relationships: { type: "array", items: { type: "string", maxLength: 180 }, maxItems: 12 },
      notable_text: { type: "array", items: { type: "string", maxLength: 120 }, maxItems: 12 },
    },
    required: [
      "image_id",
      "media_type",
      "scene_description",
      "environment",
      "ui_types",
      "entities",
      "applications",
      "activities",
      "relationships",
      "notable_text",
    ],
    additionalProperties: false,
  };
  return {
    type: "object",
    properties: { results: { type: "array", items: item } },
    required: ["results"],
    additionalProperties: false,
  };
}

export function searchSchema(imageIds: number[]) {
  return {
    type: "object",
    properties: {
      results: {
        type: "array",
        items: {
          type: "object",
          properties: {
            image_id: { type: "integer", enum: imageIds },
            independent_conditions: {
              type: "array",
              items: {
                type: "object",
                properties: {
                  condition: { type: "string", maxLength: 80 },
                  confirmed: { type: "boolean" },
                  evidence: { type: "string", maxLength: 140 },
                },
                required: ["condition", "confirmed", "evidence"],
                additionalProperties: false,
              },
              maxItems: 8,
            },
            reason: { type: "string", maxLength: 180 },
          },
          required: ["image_id", "independent_conditions", "reason"],
          additionalProperties: false,
        },
      },
    },
    required: ["results"],
    additionalProperties: false,
  };
}
