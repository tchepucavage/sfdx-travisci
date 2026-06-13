public with sharing class DatacenterCoolingAdvisor {
    private static final Decimal DEFAULT_RACK_LOAD_KW = 480;
    private static final Decimal DEFAULT_SUPPLY_TEMP_F = 68;
    private static final Decimal DEFAULT_RETURN_TEMP_F = 82;
    private static final Decimal DEFAULT_AIRFLOW_KCFM = 85;
    private static final Decimal DEFAULT_HUMIDITY_PCT = 45;
    private static final Decimal DEFAULT_OUTSIDE_TEMP_F = 72;
    private static final Decimal DEFAULT_ENERGY_PRICE = 0.12;
    private static final Decimal DEFAULT_MAX_INLET_TEMP_F = 80.6;

    @AuraEnabled(cacheable=true)
    public static CoolingPlan evaluateCoolingPlan(
        Decimal rackLoadKw,
        Decimal supplyTempF,
        Decimal returnTempF,
        Decimal airflowKcfm,
        Decimal humidityPct,
        Decimal outsideAirTempF,
        Decimal energyPricePerKwh,
        Decimal maxInletTempF,
        String coolingMode
    ) {
        CoolingInputs inputs = normalizeInputs(
            rackLoadKw,
            supplyTempF,
            returnTempF,
            airflowKcfm,
            humidityPct,
            outsideAirTempF,
            energyPricePerKwh,
            maxInletTempF,
            coolingMode
        );

        List<ActionScore> actionScores = new List<ActionScore>();
        for (CandidateAction action : buildCandidateActions(inputs.coolingMode, inputs.outsideAirTempF)) {
            actionScores.add(scoreAction(inputs, action));
        }
        actionScores.sort();

        ActionScore recommended = actionScores[0];
        CoolingPlan plan = new CoolingPlan();
        plan.recommendedAction = recommended.name;
        plan.controlInstruction = recommended.controlInstruction;
        plan.policySummary = 'DRL policy approximation selected the action with the highest reward after balancing thermal risk, predicted energy use, and control movement.';
        plan.predictedInletTempF = recommended.predictedInletTempF;
        plan.thermalHeadroomF = recommended.thermalHeadroomF;
        plan.coolingPowerKw = recommended.coolingPowerKw;
        plan.costPerHour = recommended.costPerHour;
        plan.pue = recommended.pue;
        plan.riskScore = recommended.riskScore;
        plan.confidence = calculateConfidence(recommended, actionScores);
        plan.actionScores = actionScores;
        plan.forecast = buildForecast(inputs, recommended);
        plan.alerts = buildAlerts(inputs, recommended);
        return plan;
    }

    private static CoolingInputs normalizeInputs(
        Decimal rackLoadKw,
        Decimal supplyTempF,
        Decimal returnTempF,
        Decimal airflowKcfm,
        Decimal humidityPct,
        Decimal outsideAirTempF,
        Decimal energyPricePerKwh,
        Decimal maxInletTempF,
        String coolingMode
    ) {
        CoolingInputs inputs = new CoolingInputs();
        inputs.rackLoadKw = bounded(rackLoadKw, DEFAULT_RACK_LOAD_KW, 50, 2500);
        inputs.supplyTempF = bounded(supplyTempF, DEFAULT_SUPPLY_TEMP_F, 55, 82);
        inputs.returnTempF = bounded(returnTempF, DEFAULT_RETURN_TEMP_F, 65, 105);
        inputs.airflowKcfm = bounded(airflowKcfm, DEFAULT_AIRFLOW_KCFM, 20, 350);
        inputs.humidityPct = bounded(humidityPct, DEFAULT_HUMIDITY_PCT, 15, 80);
        inputs.outsideAirTempF = bounded(outsideAirTempF, DEFAULT_OUTSIDE_TEMP_F, -20, 120);
        inputs.energyPricePerKwh = bounded(energyPricePerKwh, DEFAULT_ENERGY_PRICE, 0.01, 1);
        inputs.maxInletTempF = bounded(maxInletTempF, DEFAULT_MAX_INLET_TEMP_F, 72, 90);
        inputs.coolingMode = String.isBlank(coolingMode) ? 'CRAC' : coolingMode.trim().toUpperCase();
        if (inputs.coolingMode != 'CRAH') {
            inputs.coolingMode = 'CRAC';
        }
        return inputs;
    }

    private static List<CandidateAction> buildCandidateActions(String coolingMode, Decimal outsideAirTempF) {
        Decimal economizerBonus = outsideAirTempF <= 68 ? 0.14 : 0.05;
        if (coolingMode == 'CRAH') {
            economizerBonus += 0.04;
        }

        return new List<CandidateAction>{
            new CandidateAction('Raise supply setpoint', 'Increase supply-air setpoint by 2 F and hold fan speed.', 2, 1, 0.05, 0.25),
            new CandidateAction('Maintain current controls', 'Keep current supply-air setpoint and airflow.', 0, 1, 0, 0.10),
            new CandidateAction('Lower supply setpoint', 'Lower supply-air setpoint by 2 F for thermal recovery.', -2, 1.04, -0.02, -0.10),
            new CandidateAction('Boost airflow', 'Increase CRAH/CRAC fan airflow by 12% while holding supply temperature.', 0, 1.12, -0.03, -0.05),
            new CandidateAction('Use economizer assist', 'Blend in economizer or water-side assist and raise supply setpoint by 1 F.', 1, 1.03, economizerBonus, 0.20)
        };
    }

    private static ActionScore scoreAction(CoolingInputs inputs, CandidateAction action) {
        Decimal proposedSupplyTemp = inputs.supplyTempF + action.supplyTempDeltaF;
        Decimal effectiveAirflow = inputs.airflowKcfm * action.airflowMultiplier;
        Decimal heatRise = (inputs.rackLoadKw / effectiveAirflow) * 1.28;
        Decimal returnInfluence = (inputs.returnTempF - inputs.supplyTempF) * 0.10;
        Decimal humidityPenalty = inputs.humidityPct > 60 ? (inputs.humidityPct - 60) * 0.10 : 0;
        if (inputs.humidityPct < 35) {
            humidityPenalty = (35 - inputs.humidityPct) * 0.07;
        }
        Decimal outsidePenalty = inputs.outsideAirTempF > 85 ? (inputs.outsideAirTempF - 85) * 0.04 : 0;
        Decimal predictedInlet = proposedSupplyTemp + heatRise + returnInfluence + humidityPenalty + outsidePenalty;
        Decimal thermalHeadroom = inputs.maxInletTempF - predictedInlet;

        Decimal riskScore = calculateRiskScore(inputs, predictedInlet, thermalHeadroom);
        Decimal coolingPowerKw = calculateCoolingPower(inputs, proposedSupplyTemp, action);
        Decimal costPerHour = coolingPowerKw * inputs.energyPricePerKwh;
        Decimal pue = (inputs.rackLoadKw + coolingPowerKw) / inputs.rackLoadKw;
        Decimal qValue = calculateQValue(inputs, action, riskScore, coolingPowerKw, thermalHeadroom);

        ActionScore score = new ActionScore();
        score.name = action.name;
        score.controlInstruction = action.controlInstruction;
        score.predictedInletTempF = rounded(predictedInlet);
        score.thermalHeadroomF = rounded(thermalHeadroom);
        score.coolingPowerKw = rounded(coolingPowerKw);
        score.costPerHour = rounded(costPerHour);
        score.pue = rounded(pue);
        score.riskScore = rounded(riskScore);
        score.qValue = rounded(qValue);
        score.supplyTempSetpointF = rounded(proposedSupplyTemp);
        score.airflowKcfm = rounded(effectiveAirflow);
        return score;
    }

    private static Decimal calculateCoolingPower(CoolingInputs inputs, Decimal proposedSupplyTemp, CandidateAction action) {
        Decimal baseCoolingFactor = inputs.coolingMode == 'CRAH' ? 0.19 : 0.23;
        Decimal liftPenalty = bounded((75 - proposedSupplyTemp) * 0.012, 0, -0.08, 0.18);
        Decimal weatherPenalty = bounded((inputs.outsideAirTempF - 65) * 0.003, 0, -0.08, 0.20);
        Decimal chillerKw = inputs.rackLoadKw * baseCoolingFactor * (1 + liftPenalty + weatherPenalty - action.efficiencyBonus);
        Decimal fanKw = inputs.rackLoadKw * 0.035 * action.airflowMultiplier * action.airflowMultiplier * action.airflowMultiplier;
        Decimal minimumCoolingKw = inputs.rackLoadKw * 0.08;
        return chillerKw + fanKw < minimumCoolingKw ? minimumCoolingKw : chillerKw + fanKw;
    }

    private static Decimal calculateRiskScore(CoolingInputs inputs, Decimal predictedInlet, Decimal thermalHeadroom) {
        Decimal temperatureRisk = ramp(predictedInlet, inputs.maxInletTempF - 4, inputs.maxInletTempF + 4) * 70;
        Decimal humidityRisk = 0;
        if (inputs.humidityPct > 60) {
            humidityRisk = (inputs.humidityPct - 60) * 1.1;
        } else if (inputs.humidityPct < 35) {
            humidityRisk = (35 - inputs.humidityPct) * 0.8;
        }
        Decimal airflowRisk = thermalHeadroom < 2 ? (2 - thermalHeadroom) * 8 : 0;
        return bounded(temperatureRisk + humidityRisk + airflowRisk, 0, 0, 100);
    }

    private static Decimal calculateQValue(
        CoolingInputs inputs,
        CandidateAction action,
        Decimal riskScore,
        Decimal coolingPowerKw,
        Decimal thermalHeadroom
    ) {
        Decimal coolingRatioPenalty = (coolingPowerKw / inputs.rackLoadKw) * 90;
        Decimal headroomPenalty = absoluteValue(thermalHeadroom - 4) * 2;
        Decimal controlBias = action.rewardBias * 10;
        return bounded(100 - (riskScore * 0.65) - coolingRatioPenalty - headroomPenalty + controlBias, 0, 0, 100);
    }

    private static Decimal calculateConfidence(ActionScore recommended, List<ActionScore> actionScores) {
        if (actionScores.size() < 2) {
            return 100;
        }
        Decimal margin = recommended.qValue - actionScores[1].qValue;
        return rounded(bounded(55 + (margin * 3), 55, 55, 96));
    }

    private static List<ForecastPoint> buildForecast(CoolingInputs inputs, ActionScore recommended) {
        List<ForecastPoint> forecast = new List<ForecastPoint>();
        for (Integer hour = 1; hour <= 6; hour++) {
            Decimal hourValue = Decimal.valueOf(String.valueOf(hour));
            Decimal loadFactor = 1 + (hourValue * 0.015);
            if (hour == 3 || hour == 6) {
                loadFactor += 0.025;
            }
            Decimal weatherDrift = (hourValue - 3) * 0.7;
            CoolingInputs hourInputs = inputs.copy();
            hourInputs.rackLoadKw = inputs.rackLoadKw * loadFactor;
            hourInputs.outsideAirTempF = inputs.outsideAirTempF + weatherDrift;

            CandidateAction lockedAction = new CandidateAction(
                recommended.name,
                recommended.controlInstruction,
                recommended.supplyTempSetpointF - inputs.supplyTempF,
                recommended.airflowKcfm / inputs.airflowKcfm,
                inferEfficiencyBonus(recommended.name, inputs.coolingMode, inputs.outsideAirTempF),
                0
            );
            ActionScore projected = scoreAction(hourInputs, lockedAction);

            ForecastPoint point = new ForecastPoint();
            point.hour = hour;
            point.loadKw = rounded(hourInputs.rackLoadKw);
            point.inletTempF = projected.predictedInletTempF;
            point.coolingPowerKw = projected.coolingPowerKw;
            point.riskScore = projected.riskScore;
            forecast.add(point);
        }
        return forecast;
    }

    private static Decimal inferEfficiencyBonus(String actionName, String coolingMode, Decimal outsideAirTempF) {
        if (actionName == 'Use economizer assist') {
            Decimal bonus = outsideAirTempF <= 68 ? 0.14 : 0.05;
            return coolingMode == 'CRAH' ? bonus + 0.04 : bonus;
        }
        if (actionName == 'Raise supply setpoint') {
            return 0.05;
        }
        if (actionName == 'Lower supply setpoint') {
            return -0.02;
        }
        if (actionName == 'Boost airflow') {
            return -0.03;
        }
        return 0;
    }

    private static List<String> buildAlerts(CoolingInputs inputs, ActionScore recommended) {
        List<String> alerts = new List<String>();
        if (recommended.riskScore >= 65) {
            alerts.add('High thermal risk: validate aisle containment and consider immediate manual override.');
        }
        if (recommended.thermalHeadroomF < 2) {
            alerts.add('Thermal headroom is under 2 F; avoid raising setpoints until load or airflow improves.');
        }
        if (inputs.humidityPct > 60 || inputs.humidityPct < 35) {
            alerts.add('Humidity is outside the recommended 35-60% operating band.');
        }
        if (inputs.outsideAirTempF <= 68 && recommended.name != 'Use economizer assist') {
            alerts.add('Outdoor conditions may support additional economizer savings.');
        }
        if (alerts.isEmpty()) {
            alerts.add('No immediate thermal alarms detected for the recommended control action.');
        }
        return alerts;
    }

    private static Decimal ramp(Decimal value, Decimal low, Decimal high) {
        if (value <= low) {
            return 0;
        }
        if (value >= high) {
            return 1;
        }
        return (value - low) / (high - low);
    }

    private static Decimal bounded(Decimal value, Decimal fallback, Decimal min, Decimal max) {
        Decimal safeValue = value == null ? fallback : value;
        if (safeValue < min) {
            return min;
        }
        if (safeValue > max) {
            return max;
        }
        return safeValue;
    }

    private static Decimal rounded(Decimal value) {
        return value == null ? null : value.setScale(2, RoundingMode.HALF_UP);
    }

    private static Decimal absoluteValue(Decimal value) {
        return value < 0 ? -value : value;
    }

    public class CoolingPlan {
        @AuraEnabled public String recommendedAction { get; set; }
        @AuraEnabled public String controlInstruction { get; set; }
        @AuraEnabled public String policySummary { get; set; }
        @AuraEnabled public Decimal predictedInletTempF { get; set; }
        @AuraEnabled public Decimal thermalHeadroomF { get; set; }
        @AuraEnabled public Decimal coolingPowerKw { get; set; }
        @AuraEnabled public Decimal costPerHour { get; set; }
        @AuraEnabled public Decimal pue { get; set; }
        @AuraEnabled public Decimal riskScore { get; set; }
        @AuraEnabled public Decimal confidence { get; set; }
        @AuraEnabled public List<ActionScore> actionScores { get; set; }
        @AuraEnabled public List<ForecastPoint> forecast { get; set; }
        @AuraEnabled public List<String> alerts { get; set; }
    }

    public class ActionScore implements Comparable {
        @AuraEnabled public String name { get; set; }
        @AuraEnabled public String controlInstruction { get; set; }
        @AuraEnabled public Decimal predictedInletTempF { get; set; }
        @AuraEnabled public Decimal thermalHeadroomF { get; set; }
        @AuraEnabled public Decimal coolingPowerKw { get; set; }
        @AuraEnabled public Decimal costPerHour { get; set; }
        @AuraEnabled public Decimal pue { get; set; }
        @AuraEnabled public Decimal riskScore { get; set; }
        @AuraEnabled public Decimal qValue { get; set; }
        @AuraEnabled public Decimal supplyTempSetpointF { get; set; }
        @AuraEnabled public Decimal airflowKcfm { get; set; }

        public Integer compareTo(Object compareTo) {
            ActionScore other = (ActionScore) compareTo;
            if (qValue == other.qValue) {
                return name.compareTo(other.name);
            }
            return qValue > other.qValue ? -1 : 1;
        }
    }

    public class ForecastPoint {
        @AuraEnabled public Integer hour { get; set; }
        @AuraEnabled public Decimal loadKw { get; set; }
        @AuraEnabled public Decimal inletTempF { get; set; }
        @AuraEnabled public Decimal coolingPowerKw { get; set; }
        @AuraEnabled public Decimal riskScore { get; set; }
    }

    private class CandidateAction {
        private String name;
        private String controlInstruction;
        private Decimal supplyTempDeltaF;
        private Decimal airflowMultiplier;
        private Decimal efficiencyBonus;
        private Decimal rewardBias;

        private CandidateAction(
            String name,
            String controlInstruction,
            Decimal supplyTempDeltaF,
            Decimal airflowMultiplier,
            Decimal efficiencyBonus,
            Decimal rewardBias
        ) {
            this.name = name;
            this.controlInstruction = controlInstruction;
            this.supplyTempDeltaF = supplyTempDeltaF;
            this.airflowMultiplier = airflowMultiplier;
            this.efficiencyBonus = efficiencyBonus;
            this.rewardBias = rewardBias;
        }
    }

    private class CoolingInputs {
        private Decimal rackLoadKw;
        private Decimal supplyTempF;
        private Decimal returnTempF;
        private Decimal airflowKcfm;
        private Decimal humidityPct;
        private Decimal outsideAirTempF;
        private Decimal energyPricePerKwh;
        private Decimal maxInletTempF;
        private String coolingMode;

        private CoolingInputs copy() {
            CoolingInputs copied = new CoolingInputs();
            copied.rackLoadKw = rackLoadKw;
            copied.supplyTempF = supplyTempF;
            copied.returnTempF = returnTempF;
            copied.airflowKcfm = airflowKcfm;
            copied.humidityPct = humidityPct;
            copied.outsideAirTempF = outsideAirTempF;
            copied.energyPricePerKwh = energyPricePerKwh;
            copied.maxInletTempF = maxInletTempF;
            copied.coolingMode = coolingMode;
            return copied;
        }
    }
}
