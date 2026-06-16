import { DynamoDBClient } from "@aws-sdk/client-dynamodb";
import { DynamoDBDocumentClient, PutCommand, ScanCommand } from "@aws-sdk/lib-dynamodb";

const client = new DynamoDBClient({});
const dynamo = DynamoDBDocumentClient.from(client);

const tableName = "BlackIceData_SenSing"; 

const safeNum = (val) => {
    const n = Number(val);
    return isNaN(n) ? 0 : n;
};

export const handler = async (event) => {
    try {

        const method = event.httpMethod || (event.requestContext && event.requestContext.http && event.requestContext.http.method);


        if (method === 'GET') {
            const result = await dynamo.send(new ScanCommand({
                TableName: tableName,
                Limit: 100 
            }));

            return {
                statusCode: 200,
                headers: {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": "*" 
                },
                body: JSON.stringify(result.Items),
            };
        } 
        

        else if (method === 'POST') {
            let body = {};
            if (event.body) {
                try { body = JSON.parse(event.body); } catch (e) { console.log("JSON 파싱 에러"); }
            } else {
                body = event;
            }

            const item = {
                device_id: String(body.device_id), 
                time: String(body.time || "2000-01-01 00:00:00"),
                temperature: safeNum(body.temperature),
                humidity: safeNum(body.humidity),
                conductivity: safeNum(body.conductivity),
                latitude: String(body.latitude || "0.0"),
                longitude: String(body.longitude || "0.0")
            };

            await dynamo.send(new PutCommand({
                TableName: tableName,
                Item: item,
            }));

            return {
                statusCode: 200,
                headers: {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": "*" 
                },
                body: JSON.stringify("Data successfully received and saved to DynamoDB!"),
            };
        } 

        else {
            return {
                statusCode: 405,
                body: JSON.stringify("허용되지 않은 HTTP 메서드입니다."),
            };
        }
        
    } catch (error) {
        console.error("Error:", error);
        return {
            statusCode: 500,
            body: JSON.stringify("Error: " + error.message),
        };
    }
};